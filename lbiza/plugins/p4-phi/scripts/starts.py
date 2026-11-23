"""starts.py: the files a brief says it covers, the checkout a started session works in, and the one start the app's
suggested task card cannot hold.

A session with work it may not start itself proposes it as a suggested task card, `mcp__ccd_session__start_session`
with `initiation` `own_initiative`, and p4-phi keeps no copy of that card. desktop.md, "Start a task that Claude
suggests": "the suggestion is a card in the chat, and its buttons either start the task or keep it in this session",
its **Start** "starts the task in another session", and "the sidebar lists the started session under the current
session". The start tool's own text adds that "the user sees a card and nothing runs until they start it", and
`mcp__ccd_session__dismiss_task` withdraws a card that went stale.

Every session works in the one checkout on the paths of its `Files:` line: agent-teams.md, "Avoid file conflicts",
"Break the work so each teammate owns a different set of files." A brief's `Files:` line says what the session
covers, which the address book, routing and the path guard read.

A start request is the one start that card cannot hold: a start addressed to a puppeteer. A card is shown in the
session that proposes it and its session is listed under that session, so no card asks another session for an
orchestrator at top level. <home>/phi/start-requests.jsonl holds one row a change: `request` with the brief and `to`,
the puppeteer's id, `claimed` when a start_session call carrying its marker is about to run, and `started` when the
child's first message arrived. A withdrawn request is kept as a `started` row whose child is "withdrawn". A request
not started within EXPIRE_S is dropped. A request is never handed to the session that filed it: the puppeteer's hooks
read it here.

The brief's marker line tells p4-phi at the child's first message which request it came from.
"""

import hashlib
import json
import os
import re
import time

import relay

EXPIRE_S = 24 * 3600            # a request not started by then is dropped
MARK_RE = re.compile(r"phi start request (req-[0-9a-f]{10}) for (\S+?)\.?(?:\s|$)")
BACKGROUND_MIN = 80             # the app refuses a fresh start whose background is shorter


def path_of(home):
    return os.path.join(home, "phi", "start-requests.jsonl")


def _append(home, row):
    p = path_of(home)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# --- the files a brief says it covers, on its `Files:` line -----------------------------------------------------------
#
# The line is information: a session's record keeps it as `fileSet`, its page shows it, and the address book names
# the session as the one a message about those files goes to. It holds no start and no other session's edit.

FILES_LINE = re.compile(r"(?im)^[ \t>*-]*(?:\*\*)?(?:files?|file set)(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]*(.+?)[ \t]*$")
NO_FILES = re.compile(r"^\W*(?:none|nothing|no files?|read[- ]only)\b", re.I)
LIST_END = re.compile(r"(?<=[\w`/\\)*\"'])[.:]\s+(?=[A-Z`\"'(])")   # where the list ends and a sentence begins


def _is_root(entry, base):
    """True for the repository's root or the session's own folder: named on a `Files:` line, it is context."""
    return "/" in entry and (entry == relay.norm(base or "") or os.path.exists(os.path.join(entry, ".git")))


def files_of(brief, base=""):
    """The files a brief says it covers: [] for `Files: none`, None when it has no such line. A name or a relative
    path is resolved in the repository `base` lies in, from its root; where no repository is known, a path with a
    folder is normalized under `base` and a bare file name is kept as its lower-case name. Only the paths listed
    after `Files:` up to the end of that line are read, and only up to where the list ends and a sentence begins. A
    path that is an ancestor of another listed path, or a repository's root, is context and is left out, unless it
    is the only path on the line, so a checkout named beside the files in it never stands for the whole repository."""
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
    """The names of a `Files:` list: a piece is kept only when it is one name, backticked or plain, with at most a
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


def stopped(s):
    """True when the app's record of a session marks its last turn stopped, with `lastTurnStopped`; its next turn
    clears the mark. p4-phi's own files record no stop, so without this the address book would name a stopped session
    for the files its brief covers."""
    relay.archived_in_app(s)                      # makes sure relay.RECORD is set: phi.py hands relay the app's records
    sid = str(s.get("sessionId") or "")
    try:
        return bool(relay.RECORD and sid.startswith("local_") and relay.RECORD(sid).get("lastTurnStopped"))
    except Exception:  # noqa: BLE001
        return False


# --- the checkout a started session works in ---------------------------------------------------------------------------
#
# Every session p4-phi starts works in its starter's checkout. The app's start tool says it in its own text:
# "use_worktree false = shares this checkout and can edit it". The work is divided by the paths each session holds,
# agent-teams.md, "Avoid file conflicts": "Break the work so each teammate owns a different set of files." Section 2's
# guard, in phi.py, is what holds that. A start tool's `use_worktree` is "\"fresh\" only (rejected with \"fork\")", so
# a start drafted for a writer is always `fresh`.

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
    """What a start call drafted for `brief` passes as `use_worktree`: False for every brief, since every session
    p4-phi starts works in its starter's checkout, on the paths of its `Files:` line. One home for the answer."""
    return False


# --- a start request, addressed to a puppeteer --------------------------------------------------------------------------

def marker(rid, requester):
    return f"phi start request {rid} for {requester}."


def state(home):
    """Every request on file by its id: its request row, with its `claimed` row folded in as `by`, `at` and, when the
    call proposed a card, `card`, and its `started` row as the child's id, which is "withdrawn" for a withdrawn
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


CARD = ("a start with no puppeteer to ask is no start request: propose it as a suggested task card, "
        "`mcp__ccd_session__start_session` with `initiation` `own_initiative`, which ezexe starts in this session, "
        "and withdraw a card that went stale with `mcp__ccd_session__dismiss_task`")


def add(home, requester, title, brief, context="fresh", at=None, background="", to=""):
    """Keeps a start request to the puppeteer `to` and returns its id and True when it is new. The same brief from
    the same session, still pending, is kept once. Its background is the one given or one built from the session
    that files it, and the files its brief says it covers are kept on it. With no `to` it is refused with CARD,
    since the app's suggested task card holds every other start."""
    if not to:
        raise ValueError(CARD)
    title, brief = " ".join(str(title or "").split()), str(brief or "").strip()
    if len(title) < 3:
        raise ValueError("a start request needs the child's title")
    if len(" ".join(brief.split())) < 20:
        raise ValueError("a start request needs the child's whole brief")
    files = files_of(brief, str(relay._session(home, requester).get("cwd") or ""))
    rid = "req-" + hashlib.sha1(f"{requester}\n{title}\n{brief}\n{to}".encode("utf-8", "replace")).hexdigest()[:10]
    held = state(home).get(rid)
    if held and not held.get("started") and (time.time() if at is None else at) - float(held.get("at") or 0) <= EXPIRE_S:
        return rid, False
    at = time.time() if at is None else at
    _append(home, {"kind": "request", "id": rid, "at": at, "time": time.strftime("%Y-%m-%d %H:%M"),
                   **({"files": files} if files else {}), "to": to,
                   "requester": requester, "requesterTitle": relay._title(relay._session(home, requester)),
                   "title": title, "brief": brief, "context": "fork" if context == "fork" else "fresh",
                   "background": background_of(home, requester, background)})
    return rid, True


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
    """A start_session call carrying a request's marker is about to run, and a row keeps which session made it, with
    `card` when the call proposes a suggested task card. Returns the request id, '' when the prompt carries none."""
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
    start-requests.jsonl, so `open_rows` leaves the request out and its record stays. An unknown id, or a request
    already started or withdrawn, is refused. A request proposed as a card is named with the tool that withdraws
    the card."""
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
