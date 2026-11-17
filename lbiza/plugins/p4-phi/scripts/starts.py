"""starts.py: the write set a brief declares, and the two starts the app's suggested task card cannot hold.

A session with work it may not start itself proposes it as a suggested task card, `mcp__ccd_session__start_session`
with `initiation` `own_initiative`, and p4-phi keeps no copy of that card. desktop.md, "Start a task that Claude
suggests": "the suggestion is a card in the chat, and its buttons either start the task or keep it in this session",
its **Start** "starts the task in another session", and "the sidebar lists the started session under the current
session". The start tool's own text adds that "the user sees a card and nothing runs until they start it", and
`mcp__ccd_session__dismiss_task` withdraws a card that went stale.

A start request is a start that card cannot hold. <home>/phi/start-requests.jsonl holds one row a change: `request`
with the brief, `claimed` when a start_session call carrying its marker is about to run, with `card` when that call
proposes the card, and `started` when the child's first message arrived. A withdrawn request is kept as a `started`
row whose child is "withdrawn". A request not started within EXPIRE_S is dropped.

  after   a start that waits behind a busy writer. The card's one condition is ezexe's press: its **Start all**
          "starts each task in its own session without waiting for one task to finish before starting the next",
          and no button of it holds a start until another session is done. The gate queues a start draft whose
          files a running session holds as a request with `after`, that session's id. Once that session is not
          busy, the session that queued the request is handed its exact call, and no other session is: a start
          at a turn ezexe began there, the card at any other turn. The app nests the child under the session
          that makes the call, so the app's parent and p4-phi's agree, and the card holds the request from then
          on.
  to      a start addressed to a puppeteer. A card is shown in the session that proposes it and its session is
          listed under that session, so no card asks another session for an orchestrator at top level. A request
          filed with `to`, a puppeteer's id, is never handed to the session that filed it, and the puppeteer's
          hooks read it here.

The brief's marker line tells p4-phi at the child's first message whose child it is: p4-phi records the session that
filed the request as the child's parent, so the child's reports and its archive line go there.
"""

import hashlib
import json
import os
import re
import time

import relay

EXPIRE_S = 24 * 3600            # a request not started by then is dropped
CLAIM_S = 15 * 60               # a claimed request whose child never arrived is handed again after this
CARDS = 3                       # the app shows at most this many suggested task cards a turn
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


# --- the checkout a started session works in ---------------------------------------------------------------------------
#
# A session that writes gets a git worktree and a branch of its own, which is Claude Code's own answer to parallel
# writers. worktrees.md: "Running each Claude Code session in its own worktree gives it a separate copy of the files
# to edit, so one session can build a feature while a second fixes a bug." desktop.md, "Run a session in its own
# worktree": "Worktrees are stored in `<project-root>/.claude/worktrees/` by default." The app's start tool takes it
# as `use_worktree`, in its own text: "use_worktree false = shares this checkout and can edit it", "true = its own
# worktree". So every start call p4-phi drafts for a worker that writes passes `use_worktree: true`, and one for a
# session that only reads passes `false`.
#
# That text also says `use_worktree` is "\"fresh\" only (rejected with \"fork\")", and of a fork that "from a plain
# checkout it shares the folder", so a start drafted for a writer is always `fresh`.
#
# A new orchestrator is started with `false`. It lands its tree's work in the checkout that holds the default branch
# and syncs the store under that checkout, and worktrees.md, "How Claude Code enforces isolation", refuses both from
# inside a worktree: "Claude Code blocks a Bash, PowerShell, or Monitor command whose working directory resolves to
# the main checkout", and "blocks a Bash or Monitor command that redirects git into the main checkout". Its own work
# steps go to workers, each in a worktree.

NEW_TOP = re.compile(r"\b(?:this|it) (?:session )?is a new top session\b", re.I)   # a new orchestrator's brief line


def writes(brief, base=""):
    """True for the brief of a session that writes: its `Files:` line names a path, or it has no such line, or one
    that names no file, and its words ask for changes, as issues.writing reads them. False for `Files: none` and for
    a check, an audit, a question or a message to pass on."""
    if files_of(brief, base):
        return True
    m = FILES_LINE.search(str(brief or ""))
    if m and NO_FILES.match(LIST_END.split(m.group(1).strip(), 1)[0].strip()):
        return False
    import issues                                 # issues.py reads relay.py alone, so nothing circles back here
    return issues.writing(brief)


def use_worktree(brief, base=""):
    """What a start call drafted for `brief` passes as `use_worktree`: True for a worker that writes, which works in
    a git worktree and on a branch of its own, False for a session that only reads, which shares its starter's
    checkout, and False for a new orchestrator, which lands in the checkout that holds the default branch."""
    return not NEW_TOP.search(str(brief or "")) and writes(brief, base)


def marker(rid, requester):
    return f"phi start request {rid} for {requester}."


def state(home):
    """Every request on file by its id: its request row, with its `claimed` row folded in as `by`, `at` and, when the
    call proposed the card, `card`, and its `started` row as the child's id, which is "withdrawn" for a withdrawn
    request."""
    out = {}
    for r in relay._rows(path_of(home)):
        rid = r.get("id")
        if not isinstance(rid, str):
            continue
        if r.get("kind") == "request":
            out[rid] = dict(r)
        elif rid in out and r.get("kind") == "claimed":
            out[rid]["claimed"] = {"by": r.get("by"), "at": r.get("at"), **({"card": True} if r.get("card") else {})}
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
    """The requests free to go, oldest first: not started, not past EXPIRE_S, not claimed in the last CLAIM_S, not
    proposed as a card, which holds a request from then on, and not behind a writer that is still busy. One addressed
    to a puppeteer is not among them: that puppeteer's hooks read it."""
    at = time.time() if at is None else at
    out = []
    for r in state(home).values():
        if r.get("started") or r.get("to") or at - float(r.get("at") or 0) > EXPIRE_S:
            continue
        c = r.get("claimed") or {}
        if c and (c.get("card") or at - float(c.get("at") or 0) < CLAIM_S):
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
        if not child and c and (c.get("card") or at - float(c.get("at") or 0) < CLAIM_S):
            out.append(x)                         # handed out or shown as a card, its child not arrived yet
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


CARD = ("a start with no busy writer to wait behind and no puppeteer to ask is no start request: propose it as a "
        "suggested task card, `mcp__ccd_session__start_session` with `initiation` `own_initiative`, which ezexe "
        "starts in this session, and withdraw a card that went stale with `mcp__ccd_session__dismiss_task`")


def add(home, requester, title, brief, context="fresh", at=None, background="", after="", declared=False,
        to=""):
    """Keeps a start request and returns its id and True when it is new. The same brief from the same session, still
    pending, is kept once. Its background is the one given or one built from the session that files it. With
    `after`, a session's id, it waits behind that session while that session is a busy writer. The write set its
    brief declares is kept on it; with `declared`, a brief that declares none is refused. With `to`, a
    puppeteer's id, it asks that puppeteer for a new orchestrator. With neither it is refused with CARD, since the
    app's suggested task card holds that start."""
    if not after and not to:
        raise ValueError(CARD)
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


def call_of(r, home="", card=False):
    """The exact start_session input that starts a request, or with `card` proposes it as a suggested task card:
    always `context` fresh, so the brief says all the child needs, with `use_worktree` true when its brief writes,
    as use_worktree reads it. It carries the request's background, which the app requires: a row with none is given
    one built from the session that filed it, and one shorter than BACKGROUND_MIN is made long enough, as
    background_of does."""
    bg = str(r.get("background") or "")
    if len(bg) < BACKGROUND_MIN:
        bg = background_of(home, r["requester"], bg) if home else (
            bg + " " + background_of("", r["requester"], "")).strip()
    import plans                                   # the model and effort its brief's kind of work gets
    return plans.with_level({"initiation": "own_initiative" if card else "user_asked", "title": r["title"],
                             "context": "fresh", "use_worktree": use_worktree(r["brief"]), "background": bg,
                             "prompt": r["brief"] + "\n\n" + marker(r["id"], r["requester"])},
                            r["title"] + "\n" + r["brief"])


def freed_text(home, sid, began, at=None):
    """The line a session is handed once starts it queued behind a busy writer are free to go, each with its exact
    call: a start at a turn ezexe began, and at any other turn the suggested task card, CARDS of them a turn, which
    ezexe starts in this session. '' when none of its own is free. No other session is handed them, a puppeteer
    included, so the app nests the child under the session that queued it. No turn is told to end on a question for
    them: a proposed card holds its request, which is handed to no turn after it."""
    rows = [r for r in pending(home, at) if r.get("requester") == sid]
    if not rows:
        return ""
    rows = rows if began else rows[:CARDS]
    lines = [f"- \"{r['title']}\": `mcp__ccd_session__start_session` with "
             f"{json.dumps(call_of(r, home, card=not began), ensure_ascii=False)}" for r in rows]
    how = ("This turn ezexe began here, so start each now, with exactly the call given, before the rest of this "
           "turn's work" if began else
           "ezexe did not begin this turn, so propose each as a suggested task card, with exactly the call given, "
           "which ezexe starts in this session; the card holds it from then on, and "
           "`mcp__ccd_session__dismiss_task` withdraws one that went stale")
    return ("phi (p4-phi): starts this session queued behind a busy writer are free to go. " + how + ":\n"
            + "\n".join(lines) + "\nEach is this session's own child, in the app's nesting and in p4-phi's.")


def queued_text(rid, new, behind):
    """What a session is told when it queued a start behind a busy writer."""
    return ((f"queued as start request {rid}" if new else f"start request {rid} was already kept")
            + f" behind {behind}: once that writer is not busy, p4-phi hands this session its exact call, a start at "
              f"a turn ezexe begins here and a suggested task card, which ezexe starts here, at any other.")


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


def claim(home, prompt, by, at=None, card=False):
    """A start_session call carrying a request's marker is about to run: the request is not handed again for
    CLAIM_S, and with `card`, a call that proposes the suggested task card, not at all, since the card holds it.
    Returns the request id, '' when the prompt carries none."""
    m = MARK_RE.search(str(prompt or ""))
    if not m or m.group(1) not in state(home):
        return ""
    _append(home, {"kind": "claimed", "id": m.group(1), "by": by, "at": time.time() if at is None else at,
                   **({"card": True} if card else {})})
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
    start-requests.jsonl, so `pending`, `open_rows` and `freed_text` leave the request out and its record stays. An
    unknown id, or a request already started or withdrawn, is refused. A request proposed as a card is named with
    the tool that withdraws the card."""
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
            f"is handed to no session. Its row stays in start-requests.jsonl."
            + (" It was proposed as a suggested task card: withdraw that card with `mcp__ccd_session__dismiss_task`."
               if (r.get("claimed") or {}).get("card") else ""))
