"""book.py: the address book every session is handed, and the recipient it names before a message is sent.

The book is a directory in the sense of the FIPA Agent Management Specification, SC00023K: the white pages, each
live session by its id, and the yellow pages, what each holds. For one session it lists the live sessions of its
project's trees and of the trees its puppeteer controls, each by full title and id, with its role, its parent, the
files its brief declared on a `Files:` line and has not freed by reporting done, its owned paths, its open issue and
its workers and coworkers. It names the puppeteer as the one address for a decision of ezexe's, and the session's
parent as the address for work off its task.

  page    <session folder>/book.md, the book whole, rewritten when an entry changes.
  state   <session folder>/book.json: a digest of each entry as the session last saw it, and the flags said.
  line    beside a message: at the first look the addresses and the entries, then only the entries that changed
          since the session last saw them, each time naming the page.
  flag    at the PreToolUse of a message one session sends another, read through phi.h_go_guard: a message naming a
          file or an issue another live session holds, sent to a session that is neither that holder nor the
          session that started it, is held with that session's full title and id; a message to the puppeteer that
          names no matter of ezexe's is held with the session it belongs to. Said once for one message and target,
          so a resend goes through.

controls.PHI is phi.py, set when phi.py is imported, and every function here is called from phi.py.
"""

import hashlib
import json
import os
import re

import controls
import issues
import relay
import starts

PAGE = "book.md"
STATE = "book.json"
SHOWN = 12                       # entries in the line at a session's first look; the rest are on the page
LINE_CHARS = 2600                # of the line beside a message
PATHS_SHOWN = 4                  # of one entry's files or owned paths, in the line
ISSUE_RE = re.compile(r"(?<![\w/#])(?:([A-Za-z0-9][\w.-]*/[\w.-]+))?#(\d{1,6})\b")
ISSUE_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/(?:issues|pull)/(\d+)", re.I)
# a decision of ezexe's authority, a press the app requires, or an outcome ezexe should hear
EZEXE = re.compile(r"\bezexe\b|\b(?:approv|authori[sz]|permission|decision|decide|push|merg|publish|deploy|"
                   r"release|credential|secret|password|token|archiv|press|click|button|spend|pay|purchase|"
                   r"billing|delet|install|sign[ -]?in|log[ -]?in)\w*", re.I)


def _phi():
    return controls.PHI


# --- the entries -------------------------------------------------------------------------------------------------------

def page_path(home, sid):
    return os.path.join(relay._dir(home, sid), PAGE).replace("\\", "/")


def _state_path(home, sid):
    return os.path.join(relay._dir(home, sid), STATE)


def _chain(every, sid):
    """The sessionIds above a session in one store's records, nearest first."""
    out, cur = [], relay._parent(every.get(sid) or {})
    while cur and cur not in out and len(out) < 12:
        out.append(cur)
        cur = relay._parent(every.get(cur) or {})
    return out


def puppeteer(home, s, store=""):
    """The sessionId and store of the puppeteer over a session's tree, the session itself when it is one, and two
    empty strings when none controls it."""
    sid = str(s.get("sessionId") or "") if isinstance(s, dict) else ""
    if not sid:
        return "", ""
    every = relay._sessions(home)
    chain = _chain(every, sid)
    top = every.get(chain[-1]) if chain else s
    top = top or {"sessionId": chain[-1]}
    if controls.is_puppeteer(top, store):
        return top["sessionId"], home
    return controls.puppeteer_of(top, store)


def held_files(home, s):
    """The files a session's brief declared and it has not freed: none once its last turn reported done, or the app
    shows it stopped, as starts.writers reads them."""
    files = s.get("fileSet")
    if not isinstance(files, list) or not files:
        return []
    turns = relay._rows(os.path.join(relay._dir(home, s["sessionId"]), "turns.jsonl"))
    if turns and turns[-1].get("done") or starts.stopped(s):
        return []
    return [x for x in files if isinstance(x, str) and x]


def _issue(s):
    i = s.get("issue") if isinstance(s.get("issue"), dict) else {}
    n = i.get("number")
    return (str(i.get("repo") or ""), int(n)) if isinstance(n, int) and n > 0 else ("", 0)


def _entry(home, s, every, pid):
    sid = s["sessionId"]
    depth = len(_chain(every, sid))
    role = ("puppeteer" if sid == pid else "orchestrator" if depth == 0 else "worker" if depth == 1
            else "coworker")
    slug, n = _issue(s)
    return {"id": sid, "title": controls.full_title(sid, s), "role": role, "parent": relay._parent(s),
            "files": held_files(home, s), "owned": relay.shard_of(s), "slug": slug, "number": n, "kids": [],
            "base": str(s.get("cwd") or ""), "home": home}


def entries(home, sid, store=""):
    """Every live session in the book of `sid`, by sessionId: its own store's, and when a puppeteer is over its
    tree, the puppeteer and the live sessions of each tree the puppeteer controls, in whatever store."""
    every = relay._sessions(home)
    me = every.get(sid) or relay._session(home, sid) or {"sessionId": sid}
    pid, pstore = puppeteer(home, me, store)
    out = {}
    for k, v in every.items():
        if not relay.gone(home, v):
            out[k] = _entry(home, v, every, pid)
    if pid and pid not in out and pstore:
        p = relay._session(pstore, pid)
        if p.get("sessionId") and not relay.gone(pstore, p):
            out[pid] = _entry(pstore, p, relay._sessions(pstore), pid)
    if pid and pstore:
        p = relay._session(pstore, pid)
        for e in controls.controlled(p):
            st = str(e.get("store") or "")
            if not st or relay.norm(st) == relay.norm(home):
                continue
            theirs = relay._sessions(st)
            for k, v in theirs.items():
                chain = _chain(theirs, k)
                if k in out or relay.gone(st, v) or (chain[-1] if chain else k) != e["sessionId"]:
                    continue
                out[k] = _entry(st, v, theirs, pid)
    for e in out.values():                         # its workers or coworkers: the live sessions it started
        e["kids"] = sorted(k for k, x in out.items() if x["parent"] == e["id"])
    return out


def _rel(path, base):
    """A held path as its repository or session folder names it, else whole."""
    p = str(path or "")
    for root in (starts.repo_root(base) if base else "", base):
        r = relay.norm(root) if root else ""
        if r and p.startswith(r + "/"):
            return p[len(r) + 1:]
    return p


def _digest(e):
    keep = {k: e[k] for k in ("title", "role", "parent", "files", "owned", "slug", "number", "kids")}
    return hashlib.sha1(json.dumps(keep, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def entry_text(e, every=None, n=PATHS_SHOWN):
    """One entry in a line: "title" `id`, its role and parent, and what it holds."""
    head = f"\"{e['title']}\" `{e['id']}`, {e['role']}"
    if e["parent"]:
        head += f" under `{e['parent']}`"
    held = []
    if e["files"]:
        files = [_rel(f, e["base"]) for f in e["files"]]
        held.append("files " + ", ".join(files[:n]) + (f" and {len(files) - n} more" if len(files) > n else ""))
    if e["owned"]:
        owned = [_rel(f, e["base"]) for f in e["owned"]]
        held.append("owned paths " + ", ".join(owned[:n]) + (f" and {len(owned) - n} more" if len(owned) > n
                                                             else ""))
    if e["number"]:
        held.append(f"issue {e['slug']}#{e['number']}" if e["slug"] else f"issue #{e['number']}")
    if e["kids"]:
        kind = "workers" if e["role"] in ("orchestrator", "puppeteer") else "coworkers"
        held.append(f"{kind} " + ", ".join(f"`{k}`" for k in e["kids"][:6])
                    + (f" and {len(e['kids']) - 6} more" if len(e["kids"]) > 6 else ""))
    return head + (": " + "; ".join(held) if held else ": holds nothing yet")


def addresses(home, s, book, store=""):
    """The sentence naming the puppeteer as the address for a decision of ezexe's and the parent as the address
    for work off the session's task."""
    sid = s["sessionId"]
    pid = next((k for k, e in book.items() if e["role"] == "puppeteer"), "")
    parent = relay._parent(s)
    out = []
    if pid and pid != sid:
        out.append(f"a decision of ezexe's authority, a press the app requires or an outcome ezexe should hear goes "
                   f"to the puppeteer \"{book[pid]['title']}\" `{pid}`, and nothing else does")
    elif pid == sid:
        out.append("this session is the puppeteer, the one address for a decision of ezexe's")
    if parent:
        title = book[parent]["title"] if parent in book else controls.full_title(parent)
        out.append(f"work off this session's task goes to its parent \"{title}\" `{parent}`")
    out.append("a message about a file, an issue or a piece of work goes straight to the session that holds that "
               "file, owns that issue or started that work, named here, never through another session")
    return "; ".join(out) + "."


def _order(book, s):
    """The entries a session needs first: its parent, the puppeteer, its siblings and its own workers, then those
    that hold files, owned paths or an issue, then the rest."""
    sid, parent = s["sessionId"], relay._parent(s)

    def rank(e):
        if e["id"] == parent:
            return 0
        if e["role"] == "puppeteer":
            return 1
        if parent and e["parent"] == parent or e["parent"] == sid:
            return 2
        if e["files"] or e["owned"] or e["number"]:
            return 3
        return 4
    return sorted((e for e in book.values() if e["id"] != sid), key=lambda e: (rank(e), e["title"]))


def _load_state(home, sid):
    d = relay._read_json(_state_path(home, sid))
    return d if isinstance(d, dict) else {}


def write_page(home, s, book, store=""):
    """book.md, the book whole, written only when it changed."""
    sid = s["sessionId"]
    lines = [f"# Address book of \"{controls.full_title(sid, s)}\"", "",
             f"Session `{sid}`. The live sessions it can message, each by full title and id with what it holds. "
             + addresses(home, s, book, store), "", "## Sessions", ""]
    lines += [f"- {entry_text(e, n=50)}" for e in _order(book, s)] or ["- No other live session."]
    if sid in book:
        lines += ["", "## This session", "", f"- {entry_text(book[sid], n=50)}"]
    text = "\n".join(lines) + "\n"
    path = page_path(home, sid)
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return path
    except OSError:
        pass
    _phi().write_atomic(path, text)
    return path


def line(home, s, store="", whole=False):
    """The book beside a message: at the session's first look, or with `whole`, its addresses and entries, cut to
    SHOWN with the rest on the page; after that only the entries that changed or left since it last looked, and ''
    when none did. Each time it names the page."""
    sid = str(s.get("sessionId") or "") if isinstance(s, dict) else ""
    if not sid or not home:
        return ""
    book = entries(home, sid, store)
    page = write_page(home, s, book, store)
    state = _load_state(home, sid)
    seen = state.get("seen") if isinstance(state.get("seen"), dict) else None
    now = {k: _digest(e) for k, e in book.items() if k != sid}
    ordered = _order(book, s)
    first = whole or seen is None
    if first:
        shown = ordered
    else:
        shown = [e for e in ordered if seen.get(e["id"]) != now[e["id"]]]
    left = [] if first else [k for k in seen if k not in now]
    state["seen"] = now
    relay._write_json(_state_path(home, sid), state)
    if not first and not shown and not left:
        return ""
    if first:
        head = (f"phi (p4-phi): this session's address book, whole on {page} and rewritten when an entry changes: "
                + addresses(home, s, book, store))
        if not shown:
            return head + " No other live session holds anything yet."
    else:
        head = f"phi (p4-phi): the address book on {page} changed since this session last looked"
        head += ":" if shown else "."
    out = [f"- {entry_text(e)}" for e in shown[:SHOWN]]
    if left:
        out.append("- no longer live: " + ", ".join(f"`{k}`" for k in left[:8])
                   + (f" and {len(left) - 8} more" if len(left) > 8 else ""))
    text = head + "\n" + "\n".join(out)
    if len(shown) > SHOWN:
        text += f"\n- and {len(shown) - SHOWN} more, on the page."
    if len(text) > LINE_CHARS:
        cut = text[:LINE_CHARS].rsplit("\n", 1)[0]
        text = cut + "\n- and more, on the page."
    return text


# --- what a message names -------------------------------------------------------------------------------------------

def issues_named(text):
    """The issues a message names, as (slug or '', number), each once."""
    out = []
    for m in ISSUE_URL.finditer(str(text or "")):
        k = (m.group(1).lower(), int(m.group(2)))
        if k not in out:
            out.append(k)
    plain = ISSUE_URL.sub(" ", str(text or ""))
    for m in ISSUE_RE.finditer(plain):
        k = ((m.group(1) or "").lower(), int(m.group(2)))
        if k not in out:
            out.append(k)
    return out


def _same_file(named, base, held, hbase):
    """True when a path a message names is a file or folder an entry holds: the same absolute path, a path inside a
    held folder, the same path from the root of each one's repository, or a held bare name that is its file name."""
    if "/" not in held:
        return named.rsplit("/", 1)[-1] == held
    if named == held or relay.covers(held, named):
        return True
    a, b = _rel(named, base), _rel(held, hbase)
    return "/" in a and "/" in b and (a == b or b.endswith("/" + a) or a.endswith("/" + b))


def holders(home, s, text, store="", skip=(), book=None):
    """The live sessions a message's paths and issues belong to, files and owned paths first, each as (entry,
    what it names). The session and those above it are left out, since a parent's files cover its children's,
    and so is every id in `skip`."""
    sid = s["sessionId"]
    book = book if book is not None else entries(home, sid, store)
    base = str(s.get("cwd") or "")
    away = {sid, *skip, *_chain(relay._sessions(home), sid)}
    named = [n for n in relay.paths_in(text, base) if not relay.names_nothing(n, home, base)]
    asked = issues_named(text)
    out = []
    for e in book.values():
        if e["id"] in away:
            continue
        hit = next((f for n in named for f in e["files"] + e["owned"]
                    if not relay.names_nothing(f, e["home"], e["base"]) and _same_file(n, base, f, e["base"])), "")
        if hit:
            out.append((e, _rel(hit, e["base"]), 0, -len(hit)))
            continue
        if e["number"] and any(n == e["number"] and (not slug or slug == e["slug"].lower()) for slug, n in asked):
            out.append((e, f"{e['slug']}#{e['number']}" if e["slug"] else f"#{e['number']}", 1, 0))
    out.sort(key=lambda x: (x[2], x[3]))
    return [(e, what) for e, what, _, _ in out]


# --- the recipient named before a send ---------------------------------------------------------------------------------

def flag(home, s, target, message, store=""):
    """The reason a message from session `s` to `target` is held before it is sent, '' when it goes. Said once for
    one message and target, kept in the sender's book.json, so a resend goes through."""
    sid = str(s.get("sessionId") or "") if isinstance(s, dict) else ""
    target = _phi().safe_id(target) if target else ""
    text = str(message or "")
    if not sid or not target or target == sid or not text.strip():
        return ""
    book = entries(home, sid, store)
    if target not in book:
        return ""                                 # a name p4-phi cannot find may be the holder itself
    pid = next((k for k, e in book.items() if e["role"] == "puppeteer"), "")
    to_pup = target == pid and sid != pid and relay._parent(s) != pid
    if to_pup and EZEXE.search(text):
        return ""                                 # ezexe's: the puppeteer is its address
    # a `Files:` line declares the recipient's write set, which controls.go_text reads; it names no other's file
    got = holders(home, s, starts.FILES_LINE.sub(" ", text), store, book=book)
    reason = ""
    if got:
        e, what = got[0]
        if target in (e["id"], e["parent"]):
            return ""                             # the holder, or the session that started it
        starter = (f", started by \"{book[e['parent']]['title']}\" `{e['parent']}`"
                   if e["parent"] in book and e["parent"] != sid else "")
        reason = (f"phi (p4-phi): this message names {what}, which \"{e['title']}\" `{e['id']}` holds{starter}, "
                  f"so it belongs to that session and not to \"{book[target]['title']}\" `{target}`. Send it to "
                  f"`{e['id']}` with SendMessage instead.")
    elif to_pup:
        if any(not holders(home, s, f, store, book=book) for f in issues.findings(text)):
            return ""                             # a finding no live session covers goes up for an issue
        parent = relay._parent(s)
        ptitle = book[parent]["title"] if parent in book else controls.full_title(parent) if parent else ""
        where = (f"work off this session's task goes to its parent \"{ptitle}\" `{parent}`" if parent
                 else "this session's own work stays in its own tree, with its own workers")
        reason = (f"phi (p4-phi): this message names no decision of ezexe's, no press the app requires and no "
                  f"outcome ezexe should hear, so it is not the puppeteer \"{book[target]['title']}\" `{target}`'s: "
                  f"{where}, and a file or an issue another session holds goes to that session, by the address "
                  f"book on {page_path(home, sid)}.")
    if not reason:
        return ""
    key = hashlib.sha1(f"{target}\n{' '.join(text.split())}".encode("utf-8")).hexdigest()[:12]
    state = _load_state(home, sid)
    said = [k for k in state.get("flagged") or [] if isinstance(k, str)]
    if key in said:
        return ""
    state["flagged"] = (said + [key])[-60:]
    relay._write_json(_state_path(home, sid), state)
    return reason + " Said once for this message and recipient, so sending it again as it is goes through."


def holder_line(home, s, finding, store="", skip=()):
    """The session a `Finding:` line belongs to, as "title" `id` and what it names, '' when no live session holds
    its file or owns its issue."""
    got = holders(home, s, finding, store, skip=skip)
    if not got:
        return ""
    e, what = got[0]
    return f"\"{e['title']}\" `{e['id']}`, which holds {what}"
