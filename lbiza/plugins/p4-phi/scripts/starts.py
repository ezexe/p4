"""starts.py: start requests, the children a session wants and cannot start, kept in the store.

The app refuses `mcp__ccd_session__start_session` with `initiation` `user_asked` in a turn ezexe did not begin, such
as a child's turn that another session's message started or an app event, and anthropics/claude-code#109282 reports
that refusal as a bug. Such a session shows the child as a suggested task card first, as phi._split_full says, and
files a start request with `phi.py request "<title>" --brief "<brief>"` only when the card is refused too.

At the next turn ezexe begins in the session that filed a request, that session is handed each of its pending
requests, one line each with the exact call, and no other session is handed them. The app nests a child under the
session that makes the start call, so the app's parent and p4-phi's agree. The brief's marker line tells p4-phi at the
child's first message whose child it is: p4-phi records the session that filed the request as the child's parent, so
the child's reports and its archive line go there. A request not started within EXPIRE_S is dropped.

Until then the session waits on ezexe by a click: each turn ezexe did not begin ends on a blocked wrap-up whose
question names the requests it holds and whose first button starts them, so the app marks it as needing ezexe and
the press of that button is the turn ezexe begins there. A puppeteer names such a session as a link and
starts none of its requests, as controls.py says.

A request filed with `to`, a puppeteer's id, asks that puppeteer for a new orchestrator: it is
never handed to the session that filed it, and the puppeteer's hooks read it here.

<home>/phi/start-requests.jsonl holds one row a change: `request` with the brief, `claimed` when a start_session
call carrying its marker is about to run, and `started` when the child's first message arrived. A withdrawn request
is kept as a `started` row whose child is "withdrawn".

A request can wait behind a busy writer: the gate queues a start draft whose files a running session holds as a
request with `after`, that session's id, and the request is handed out only once that session is not busy.
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
BACKGROUND_MIN = 80             # the app refuses a fresh start whose background is shorter


def path_of(home):
    return os.path.join(home, "phi", "start-requests.jsonl")


def _append(home, row):
    p = path_of(home)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# --- write sets: the files a brief declares on its `Files:` line ------------------------------------------------------
#
# FILES_WANTED states the rule a session meets, one writer per file in the single work tree. This section reads the
# write set a brief declares and finds where two write sets overlap.

FILES_LINE = re.compile(r"(?im)^[ \t>*-]*(?:\*\*)?(?:files?|file set)(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]*(.+?)[ \t]*$")
NO_FILES = re.compile(r"^\W*(?:none|nothing|no files?|read[- ]only)\b", re.I)
FILES_WANTED = ("a brief declares its write set: add a line `Files: <each path this session may write, comma "
                "separated>`, or `Files: none` for a session that writes nothing. One writer per file: a start whose "
                "write set overlaps a live session's is held until that session reports done, tasks that share a file "
                "go to one child as a serial run, and tasks with disjoint files each get a child.")


LIST_END = re.compile(r"(?<=[\w`/\\)*\"'])[.:]\s+(?=[A-Z`\"'(])")   # where the list ends and a sentence begins


def _is_root(entry, base):
    """True for the repository's root or the session's own folder: named on a `Files:` line, it is context."""
    return "/" in entry and (entry == relay.norm(base or "") or os.path.exists(os.path.join(entry, ".git")))


def files_of(brief, base=""):
    """The write set a brief declares: [] for `Files: none`, None when it has no such line. A name or a relative path
    is resolved in the repository `base` lies in, from its root; where no repository is known, a path with a folder is
    normalized under `base` and a bare file name is kept as its lower-case name. Only the paths listed after `Files:`
    up to the end of that line are read, and only up to where the list ends and a sentence begins. A path that is
    an ancestor of another listed path, or a repository's root, is context and is not held, unless it is the only
    path on the line, so a checkout named beside the files in it never holds the whole repository."""
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


def repo_root(base):
    """The root of the git repository `base` lies in, the nearest folder up from it with a .git, or '' when none
    does, so a name on a Files line belongs to that repository and never to another one beside it."""
    d = os.path.abspath(base) if base else ""
    while d:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return ""
        d = up
    return ""


def _listed(value, base):
    """The names of a `Files:` list: a piece is held only when it is one name, backticked or plain, with at most a
    trailing parenthetical such as `(new)`; a piece that is a clause of words, as `the tests only`, names no file."""
    out = []
    for tok in re.split(r"\s*(?:,|;|\band\b)\s*", value):
        piece = re.sub(r"\s*\([^()]*\)\s*$", "", tok.strip()).strip().strip("'\"").rstrip(".").strip()
        lead = re.match(r"(`[^`\s]+`)\s+[A-Z]", piece)
        if lead:
            piece = lead.group(1)                       # a name, then a new sentence whose full stop was left out
        if not piece or re.search(r"\s", piece.replace("`", "")) or piece.count("`") not in (0, 2):
            continue
        name = piece.strip("`'\"").rstrip(".")
        if not name:
            continue
        root = repo_root(base)
        if root:
            entry = relay.norm(name, root)              # a name of the repository the session writes in
        else:
            entry = relay.norm(name, base) if re.search(r"[\\/]", name) else name.lower()
        if entry not in out:
            out.append(entry)
    return out


def files_overlap(a, b):
    """The entries two write sets share: equal or nested paths, or a bare name that is the other's file name. A bare
    name is left only where files_of knew no repository, so names in two known repositories never meet here."""
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
    """A session and every session above it: a parent's write set covers its children's and never holds them."""
    out, cur = [], sid
    while cur and cur not in out and len(out) < 12:
        out.append(cur)
        cur = relay._parent(relay._session(home, cur))
    return out


def stopped(s):
    """True when the app's record of a session marks its last turn stopped, with `lastTurnStopped`; its next turn
    clears the mark. p4-phi's own files record no stop, so without this a stopped session would keep holding its
    write set."""
    relay.archived_in_app(s)                      # makes sure relay.RECORD is set: phi.py hands relay the app's records
    sid = str(s.get("sessionId") or "")
    try:
        return bool(relay.RECORD and sid.startswith("local_") and relay.RECORD(sid).get("lastTurnStopped"))
    except Exception:  # noqa: BLE001
        return False


def writers(home, skip=()):
    """The live sessions that declared files and have not reported done, each as its sessionId, title and write set.
    An archived session holds nothing, and neither does one the app shows as stopped."""
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
    """Who holds a start and the files they share: the first live writer, or request handed out before it, whose
    write set overlaps `files`. Returns '' and [] when the start is free to go."""
    if not files:
        return "", []
    for sid, title, theirs in writers(home, skip=above(home, requester)):
        hit = files_overlap(files, theirs)
        if hit:
            return f"\"{title}\" `{sid}`", hit
    for r in earlier:
        hit = files_overlap(files, r.get("files") or [])
        if hit:
            return f"start request {r.get('id')} \"{r.get('title')}\"", hit
    return "", []


def marker(rid, requester):
    return f"phi start request {rid} for {requester}."


def state(home):
    """Every request on file by its id: its request row, with its `claimed` row folded in as `by` and `at`, and its
    `started` row as the child's id, which is "withdrawn" for a withdrawn request."""
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
    CLAIM_S. One addressed to a puppeteer is not among them: that puppeteer's hooks read it."""
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
        if not who:                               # held while a live writer or an earlier start has its files
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
            continue                              # its child arrived: writers() answers for it, live or not
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
    """The background of a request's start call: the one given, else one that names the session that files it, by
    its title, and the store's project, never shorter than BACKGROUND_MIN characters. It quotes no word of that
    session's own prompt, which was sent to it and not to the child: the brief says what the child is to do."""
    text = " ".join(str(given or "").split())
    if not text:
        s = relay._session(home, requester)
        project = relay.norm(os.path.dirname(os.path.dirname(os.path.abspath(home))))
        text = f"Requested by the session \"{relay._title(s)}\" `{requester}` in the project {project}."
    if len(text) < BACKGROUND_MIN:
        text += (" phi (p4-phi) carried this start request through the store; the brief says what the child must "
                 "do and leave done.")
    return text


def add(home, requester, title, brief, context="fresh", at=None, background="", after="", declared=False,
        to=""):
    """Keeps a start request and returns its id and True when it is new. The same brief from the same session, still
    pending, is kept once. Its background is the one given or one built from the session that files it. With
    `after`, a session's id, it waits behind that session while that session is a busy writer. The write set its
    brief declares is kept on it; with `declared`, a brief that declares none is refused. With `to`, a
    puppeteer's id, it asks that puppeteer for a new orchestrator."""
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
    """The exact start_session input that starts a request: always `context` fresh, so the brief says all the child
    needs. It carries the request's background, which the app requires: a row with none is given one built from the
    session that filed it, and one shorter than BACKGROUND_MIN is made long enough, as background_of does."""
    bg = str(r.get("background") or "")
    if len(bg) < BACKGROUND_MIN:
        bg = background_of(home, r["requester"], bg) if home else (
            bg + " " + background_of("", r["requester"], "")).strip()
    import plans                                   # the model and effort its brief's kind of work gets
    return plans.with_level({"initiation": "user_asked", "title": r["title"], "context": "fresh",
                             "use_worktree": False, "background": bg,
                             "prompt": r["brief"] + "\n\n" + marker(r["id"], r["requester"])},
                            r["title"] + "\n" + r["brief"])


def hand_text(home, sid, at=None):
    """The lines a session is handed at a turn ezexe began in it: each pending request it filed itself, with
    its exact call; '' when none of its own is pending. No other session is handed a request, a puppeteer
    included, so the app nests the child under the session that filed it."""
    rows = [r for r in pending(home, at) if r.get("requester") == sid]
    if not rows:
        return ""
    lines = [f"- \"{r['title']}\": `mcp__ccd_session__start_session` with "
             f"{json.dumps(call_of(r, home), ensure_ascii=False)}" for r in rows]
    return ("phi (p4-phi): start requests this session filed in turns ezexe did not begin. "
            "This turn ezexe began here, so start each now, with exactly the call given, before the rest of this "
            "turn's work:\n" + "\n".join(lines) + "\n"
            "Each is this session's own child, in the app's nesting and in p4-phi's.")


BUTTONS = ("Start it", "Start them")   # the first reply button of the wrap-up a session holding requests ends on


def wait_text(titles):
    """How a session that holds start requests ends a turn ezexe did not begin: on a blocked wrap-up whose question
    names them and whose first button starts them, so the app marks it as needing ezexe and one click in it is the
    turn ezexe begins there."""
    one = len(titles) == 1
    ask = (f"Start \"{titles[0]}\" here?" if one else f"Start {len(titles)} sessions here: "
           + ", ".join(f"\"{t}\"" for t in titles[:3]) + (" and more?" if len(titles) > 3 else "?"))
    return (f"End this turn with `mcp__ccd_turn__wrap_up` with `blocked` true, the question \"{ask}\", cut to fit, "
            f"and the reply button \"{BUTTONS[0] if one else BUTTONS[1]}\" first: the app marks this session as "
            f"needing ezexe, and that one click is a turn ezexe began here, which starts {'it' if one else 'them'} "
            f"with the exact call{'' if one else 's'} p4-phi hands then.")


def requested_text(rid, new, home=""):
    """What a session is told when it kept a start request: no other session is handed it, and it waits on ezexe by
    the click wait_text names, its question naming every start request the session holds."""
    asker = state(home).get(rid, {}).get("requester") if home else ""
    titles = [r["title"] for r in open_rows(home) if asker and r.get("requester") == asker and not r.get("to")] \
        if home else []
    return ((f"kept as start request {rid}" if new else f"start request {rid} was already kept") +
            ". No other session is handed it: it waits on ezexe's click in this session, since the app refuses this "
            "start in a turn ezexe did not begin, and the next turn ezexe begins here starts it as this session's own "
            "child. Carry on with the rest of the task. " + wait_text(titles or [rid]))


def waiting_text(home, sid, at=None):
    """The line a session is handed at a turn ezexe did not begin while it holds start requests that a turn of
    ezexe's would start: it ends this turn on the click wait_text names too. '' when it holds none."""
    titles = [r["title"] for r in pending(home, at) if r.get("requester") == sid]
    if not titles:
        return ""
    n = len(titles)
    return (f"phi (p4-phi): this session holds {n} start request{'s' if n != 1 else ''} that "
            f"{'waits' if n == 1 else 'wait'} on ezexe's click here, since the app refuses a start in a turn ezexe "
            f"did not begin. " + wait_text(titles))


def asked_text(rid, new, title, pid, ptitle):
    """What a session is told when it asked its puppeteer for a new orchestrator: the
    puppeteer as the link ezexe opens to begin the turn that starts it."""
    return ((f"kept as request {rid} to this session's puppeteer" if new
             else f"request {rid} was already kept") +
            f": \"{title}\" is handed to it at the next turn ezexe begins there, by the link "
            f"{relay.link_of({'id': pid, 'title': ptitle or pid})} ezexe opens to send it one message, and it starts "
            "the session, files it in this environment's section and takes it under control, or declines it. Start "
            "nothing for it here: name that link to ezexe in this turn's report, and carry on with the rest of the "
            "task.")


def claim(home, prompt, by, at=None):
    """A start_session call carrying a request's marker is about to run: the request is not handed again for
    CLAIM_S. Returns the request id, '' when the prompt carries none."""
    m = MARK_RE.search(str(prompt or ""))
    if not m or m.group(1) not in state(home):
        return ""
    _append(home, {"kind": "claimed", "id": m.group(1), "by": by, "at": time.time() if at is None else at})
    return m.group(1)


def requester_of(home, prompt):
    """The request id and the session that filed it, which a started session's first message names by its marker;
    '' and '' for none."""
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
    """Withdraws a pending start request by its id and returns the line to print. The withdrawal is kept as a row in
    start-requests.jsonl, so `pending`, `open_rows` and `hand_text` leave the request out and its record stays. An
    unknown id, or a request already started or withdrawn, is refused."""
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
