"""controls.py: a puppeteer and the sessions it controls.

A puppeteer is known by the session tree: a session nobody started that started an orchestrator which is still live.
The orchestrators it started stay attached under it, as its workers, and each is the top of a tree of its own. The
watcher every orchestrator has is puppeteer.py's and is another thing.

  the link     the app nests a session under the session that calls the start tool, and no tool moves it after. So the
               sessions a puppeteer controls are read, never recorded by hand: the live sessions whose record names
               it as their starter, by the store's records and by the app's newest records for one that has sent no
               message yet. `controlled` gives them, each as a row of its sessionId and the store its folder is in,
               and `puppeteer_of` gives a session's puppeteer: its starter, where nobody started that starter. Each
               side reads the other's store and neither writes into it.
  the board    <the puppeteer's folder>/board.md, rewritten by its hooks and the `controls` command: each
               controlled session in a line with the path of its page, the requests addressed to the
               puppeteer, the `Finding:` lines of the reports of the controlled trees, the feedback and user memories
               ezexe changed during the run and its notes by kind. After a compaction its path is the first thing the
               puppeteer is handed.
  findings     no session publishes a new issue on its own. A finding goes up in the reports of the session tree as one
               `Finding:` line, and one session publishes what needs an issue and places the session that resolves
               it: the session nobody started at the top of the tree, a puppeteer or an orchestrator. `publisher`
               names that session, and a `gh issue create` in any other session is refused with its title.
  a boundary   a controlled tree has closed, or every controlled session is idle with no request waiting. The
               puppeteer is told once to keep what is not on its board with `note`. Claude Code compacts a
               session by itself and p4-phi asks ezexe nothing about it. p4-phi speaks only
               when one of its hooks fires, so a boundary reached while the puppeteer is idle is told
               beside its next message. No idle notice can be asked of a controlled session, since the
               desktop app runs each and `SendMessage` with `notify_when_idle` serves a session outside
               the app alone, so `idle_watch` says once, for each controlled session that works, what
               does tell the puppeteer of its turn's end. A command hook with `asyncRewake` could wake
               it at once, and p4-phi uses none.
  open issues  an open issue of a repository a controlled session works in is the puppeteer's to resolve. When a
               controlled tree has closed or a controlled session has reported done, the puppeteer is handed the
               ones no live session holds, each once, beside the running orchestrator whose topic covers it or as
               the start of a new orchestrator, and none as a choice of ezexe's. Its own watcher lists them from
               GitHub at its slow looks, so no hook reads GitHub for the line.
  archiving    the app asks ezexe before it archives a session, except in Auto mode and Bypass permissions mode,
               desktop.md, "Work across sessions", and the tool refuses a session with live background work. The
               settings keeper writes no ask rule on the archive tool. p4-phi only names the controlled sessions
               its records hold complete, which no tool of the app tells: no open plan step and no closing commit
               unpushed. Where a project turns `phi.upkeep` on, the line that names a complete session holds its
               archive call, and no line leaves the archive to ezexe.
  requests    a controlled session that would start a new orchestrator writes `request ... --to-puppeteer`
               into its own store; the puppeteer's hooks read it there, and what became of it is kept on
               the puppeteer's record, where the hook of the session that filed it reads it.
"""

import hashlib
import json
import os
import re
import time

import issues
import p4conf
import plans
import relay
import rows
import starts

PHI = None                       # phi.py's own module, handed over when phi.py imports this one

REASON_MIN = 12                  # characters of a reason that says something
RECENT = 120                     # the app's newest records looked through for sessions a puppeteer started
SHARE = 2                        # content words a message shares with a controlled session's topic to be sent there
UPKEEP = False                   # phi.project_conf sets it from p4.json phi.upkeep


def _watcher():
    import puppeteer
    return puppeteer


def _conf(store, key):
    try:
        return p4conf.section(store, "phi", write=False).get(key) if store else None
    except Exception:  # noqa: BLE001
        return None


def full_title(sid, s=None):
    """A session's whole title as the app lists it, else what p4-phi holds."""
    return PHI.clean(PHI.app_record(sid).get("title")) or PHI.title_of(s or {"sessionId": sid})


def link(sid, s=None):
    """A session as the link ezexe opens it by: [its full title](#its sessionId)."""
    return relay.link_of({"id": sid, "title": full_title(sid, s)})


def out_of_tree(s):
    """True for a session p4-phi holds as stale, counted as archived or archived, or that the app has archived, read
    without writing to its store."""
    return bool(not isinstance(s, dict) or s.get("stale") or s.get("doneRetired") or s.get("archived")
                or relay.archived_in_app(s))


def store_of(sid):
    """The store a session's tree lives in, by the app's record, and an empty string when it cannot be told."""
    rec = PHI.app_record(sid)
    return (PHI.own_store(rec, sid) or PHI.home_of_record(rec) or "").replace("\\", "/")


def page_of(store, sid):
    return PHI.page_path(store, sid) if store else ""


def _children(home, sid):
    """The live desktop sessions `sid` started: by the store's records, and by the app's newest records for one
    that has sent no message yet."""
    sid = str(sid or "")
    if not sid:
        return []
    out = [k for k, v in relay._sessions(home).items() if PHI.spawned_from(v) == sid and live(k)] if home else []
    return out + [k for k in started_by(sid) if k not in out]


def controlled(s, home=""):
    """The sessions a puppeteer controls: the live desktop sessions it started, each as a row with the store its
    folder is in. Nothing records them by hand."""
    sid = str(s.get("sessionId") or "") if isinstance(s, dict) else ""
    if not sid or PHI.spawned_from(s):
        return []
    home = home or store_of(sid)
    return [{"sessionId": k, "store": store_of(k) or home, "time": ""} for k in _children(home, sid)]


def is_puppeteer(s, store=""):
    """True for a puppeteer: a session nobody started that started an orchestrator which is still live."""
    return bool(controlled(s, store))


def puppeteer_of(s, store=""):
    """The sessionId and store of the session that started this one, where nobody started that one, and two
    empty strings otherwise."""
    pid = PHI.spawned_from(s) if isinstance(s, dict) else ""
    if not pid:
        return "", ""
    pstore = store_of(pid) or store
    p = PHI.load_session(pstore, pid) if pstore else {}
    return (pid, pstore) if p.get("sessionId") and not PHI.spawned_from(p) else ("", "")


# --- where a controlled session stands ---------------------------------------------------------------------------------

# One read of each controlled session in one hook, and what git and GitHub answered kept, ezexe/p4#216. A puppeteer's
# message hook asked where a controlled session stands in its reports, its boundary and its board, and its Stop hook in
# the sessions it waits on and its board, each time running git for every closing commit and gh for every issue, which
# took the hooks past their limits. Inside a hook, which phi.hook_main marks with one_hook, standing is read once for
# a session and every caller gets that answer. A commit found landed stays landed and an issue found closed is kept
# by its number, in the store's phi/.cache/known.json, so no later hook runs git or gh for them.
_ONE = [None]                    # inside a hook, {(store, sid): standing's answer}; None outside one
KNOWN = ("phi", ".cache", "known.json")
KNOWN_MOST = 2000                # the commits and the issues one store keeps


def one_hook(on):
    """Marks a hook's start and its end: between them each controlled session is read once."""
    _ONE[0] = {} if on else None


def _known(store):
    d = relay._read_json(os.path.join(store, *KNOWN)) if store else {}
    return d if isinstance(d, dict) else {}


def _know(store, kind, key):
    if not store:
        return
    d = _known(store)
    have = [x for x in d.get(kind) or [] if isinstance(x, str)]
    if key not in have:
        d[kind] = (have + [key])[-KNOWN_MOST:]
        try:
            relay._write_json(os.path.join(store, *KNOWN), d)
        except OSError:
            pass


def landed_once(store, path, sha, closes):
    """issues.landed, with a commit it found landed kept by its sha, so git is asked once for it."""
    if sha in (_known(store).get("landed") or []):
        return True
    got = issues.landed(path, sha, closes)
    if got:
        _know(store, "landed", sha)
    return got


def closed_once(store, slug, n):
    """True when GitHub shows the issue closed, with one it showed closed kept by its number, so gh is asked once."""
    key = f"{str(slug).lower()}#{n}"
    if key in (_known(store).get("closed") or []):
        return True
    got = issues.issue_state(slug, n) == "CLOSED"
    if got:
        _know(store, "closed", key)
    return got


def standing(store, sid):
    """Where a controlled session stands: _standing's answer, read once for a session inside one hook."""
    memo = _ONE[0]
    key = (os.path.normcase(os.path.abspath(store)) if store else "", sid)
    if memo is not None and key in memo:
        state, against = memo[key]
        return state, list(against)
    state, against = _standing(store, sid)
    if memo is not None:
        memo[key] = (state, list(against))
    return state, against


def _standing(store, sid):
    """Where a controlled session stands, read from the app's record and its own store and written nowhere but for
    the answers of git and GitHub it keeps. Returns its state, one of archived, unread, working, open, shown done and
    not shown done, and the list of what p4-phi's records hold against archiving it."""
    rec = PHI.app_record(sid)
    if not rec:
        return "unread", ["the app holds no record of it on this machine"]
    if rec.get("isArchived"):
        return "archived", []
    s = PHI.load_session(store, sid) if store else {}
    if not s.get("sessionId"):
        return "unread", ["p4-phi finds no record of it in a store, so its turn and steps are unread"]
    against = []
    working = _watcher().working(store, sid)
    if working:
        against.append("its last message has no turn's end recorded after it, so it is mid-turn")
    steps = plans.open_steps(store, sid)
    try:
        commits = relay.closing_commits(store, sid, s)
    except Exception:  # noqa: BLE001
        commits = []
    if steps and not issues_closed(s, commits, store):   # once its issues are closed, a stale step holds nothing
        against.append(f"{len(steps)} open plan step{'s' if len(steps) != 1 else ''}, the next "
                       f"\"{PHI.cut(PHI.clean(steps[0].get('content')), 80)}\"")
    tasks = _watcher().held_tasks(store, sid)
    if tasks:
        against.append(f"{len(tasks)} background task{'s' if len(tasks) != 1 else ''} still running at its last "
                       f"turn's end: "
                       + "; ".join(tasks[:3]))
    for kid, k in sorted(relay._sessions(store).items()):
        if kid == sid or out_of_tree(k) or sid not in PHI.chain_of(store, kid):
            continue
        if _watcher().working(store, kid) or plans.open_steps(store, kid):
            against.append(f"\"{full_title(kid, k)}\" under it is still working")
    for path, sha, _, closes in commits:
        try:
            if not landed_once(store, path, sha, closes):
                against.append(f"commit {sha}, which closes {', '.join(closes)}, is on no remote branch, and no "
                               f"commit there closes the same issue or carries the same change")
        except Exception:  # noqa: BLE001
            pass
    turns = PHI.load_turns(store, sid)
    every = plans.load(store, sid).get("steps") or []
    shown = bool(turns and turns[-1].get("done")) or bool(every) and not steps
    return ("working" if working else "open" if against else "shown done" if shown else "not shown done"), against


def issues_closed(s, commits, store=""):
    """True when a session names issues, by its own issue or its closing commits, and GitHub shows each closed. With
    `store`, an issue GitHub showed closed is kept there and not asked for again."""
    named = set()
    held = s.get("issue") if isinstance(s.get("issue"), dict) else {}
    if held.get("repo") and str(held.get("number") or "").isdigit():
        named.add((held["repo"], int(held["number"])))
    for path, _, _, closes in commits:
        for c in closes:
            slug, _, n = str(c).rpartition("#")
            slug = slug or issues.github_of(path)
            if slug and n.isdigit():
                named.add((slug, int(n)))
    return bool(named) and all(closed_once(store, slug, n) for slug, n in sorted(named))


def last_report(store, sid):
    """When a session's last report came and its first line, and two empty strings when it has no turn."""
    turns = PHI.load_turns(store, sid) if store else []
    if not turns:
        return "", ""
    text = str(turns[-1].get("report") or "").strip().split("\n", 1)[0]
    return str(turns[-1].get("time") or ""), PHI.cut(PHI.clean(text), 200)


# --- the puppeteer and its controlled sessions ----------------------------------------------------------------

RULE = (
    "This session is a puppeteer: it is a session nobody started that started an orchestrator, so it controls the "
    "orchestrators it started, which stay attached under it as its workers. `{cmd} controls` prints where each "
    "stands. Its board is {board}, and what "
    "p4-phi cannot see goes on it through `{cmd} note`. The app continues it with a short note when a session it "
    "started ends a turn, and p4-phi hands it one line per controlled session's turn; it relays none of these to "
    "ezexe and acts only on what is ezexe's. The archive calls are {archives}. Work ezexe gives it on a controlled "
    "session's topic goes straight to that orchestrator in one SendMessage holding {restate}, a `Files:` line and "
    "what done looks like, and that session briefs and starts a worker of its own for it. A task on no "
    "orchestrator's topic gets a new orchestrator that this session starts, and a task that is its own it does "
    "itself. It checks the orchestrators for stalls and context, and tunes their effort from their reports, with no "
    "one asking, by `mcp__ccd_session_mgmt__set_session_effort`, logging each change on its board. It changes a "
    "running session's model, by `mcp__ccd_session_mgmt__set_session_model`, only where effort alone does not fit "
    "that session's work and its context is worth keeping, and starts a new session otherwise. A `Finding:` line "
    "stays on its board until a note of kind `published` holds its text: this session publishes the issues that "
    "flow up, once it has checked them against the open issues and the running sessions, and records each with "
    "`{cmd} note \"<the finding> as #N\" --source \"<the issue>\" --kind published`. It shows ezexe a result in its "
    "reply as a short table or list, with the full page kept in the store's notes, and publishes no Artifact and "
    "sends no file unless ezexe asks.{asks}")
# The two places of RULE that word the archive: who answers for the call, and the sentence that ends the rule. With
# `phi.upkeep` on, the call is the upkeep line's and no sentence leaves it to ezexe.
ARCHIVES = ("which the app puts to ezexe on its approval card outside Auto mode and Bypass permissions mode",
            " The app asks ezexe on its approval card before each archive call it makes, except in Auto mode and "
            "Bypass permissions mode.")
ARCHIVES_UPKEEP = ("which its upkeep line names for each finished, landed session it started", "")
PAIR_ASKS = (" The app asks ezexe on its approval card before any archive call on its tree, except in Auto mode and "
             "Bypass permissions mode.")
PAIR = (
    "This session is controlled by a puppeteer: \"{title}\" `{pid}` started it, and this session stays attached "
    "under it. This session orchestrates its own tree itself. That puppeteer is the one address for a decision "
    "of ezexe's authority, a press the app requires or an outcome ezexe should hear; a message about a file, an "
    "issue or a piece of work goes straight to the session that holds that file, owns that issue or started that "
    "work, as the address book names it, never through the puppeteer.{asks}")
PAIR_OVER = ("This session has left the control of its puppeteer: \"{title}\" `{pid}` no longer controls it. This "
             "session starts its own new orchestrators.")


# --- a state page, and when a session clears itself --------------------------------------------------------------

CLEAR_AT = 60                    # percent of a session's context past which it clears itself and resumes from its page


def live(sid):
    """True while the app holds a record of the session and has not archived it."""
    rec = PHI.app_record(sid)
    return bool(rec) and not rec.get("isArchived")


STATE_NAME = "state.md in its own scratchpad directory, the one the app names"


def state_page(s):
    """A session's state page: state.md in the app's scratchpad of its first turn, never under .claude,
    where every write asks ezexe."""
    pad = str(s.get("scratchpadDir") or "").rstrip("/")
    return f"{pad}/state.md" if pad else STATE_NAME


STATE_IN_TASK = re.compile(r"\bState page:\s*(\S+?)[.,;]?(?=\s|$)")


def page_of_task(home, s):
    """The state page a session keeps: the one its p4-phi task names, else its own where it was told to keep one;
    '' for none."""
    m = STATE_IN_TASK.search(PHI.clean(s.get("task")))
    if m:
        return m.group(1).replace("\\", "/")
    if s.get("pageTold"):
        return state_page(s)
    return ""


# The description of `mcp__ccd_session_mgmt__clear_session` has "The transcript starts over empty while the session
# keeps its folder, model, permissions and settings", for this session or "an idle session this session started". So a
# session that keeps a state page can clear a coworker, and a coworker with no page would resume from nothing.
KEEP_PAGE = ("phi (p4-phi): \"{title}\" `{pid}`, which started this session, keeps a state page, and this session "
             "keeps none. Keep this session's task, its queue, its open items and the sessions it works with by id on "
             "a state page of its own, {page}, rewritten at each turn's end, so it resumes from that page after a "
             "compaction or a clear, its own or one \"{title}\" makes. Write the page before this turn ends. Said "
             "once: each later `wrap_up` asks for the page brought up to date.")


def keep_line(home, s):
    """At a turn's `wrap_up`, for a coworker that keeps no state page while the session that started it keeps one:
    one line, said once, that tells it to keep a page and where, state_page's place in its own scratchpad. Its record
    then holds `pageTold`, so page_of_task gives that page from the next `wrap_up` on. '' for any other session."""
    pid = PHI.spawned_from(s)
    up = PHI.load_session(home, pid) if pid else {}
    if not up.get("sessionId") or not page_of_task(home, up):
        return ""
    s["pageTold"] = True
    PHI.save_session(home, s)
    return KEEP_PAGE.format(title=full_title(pid, up), pid=pid, page=state_page(s))


def state_first(home, s):
    """A session that keeps a state page, after a compaction or a clear: that page's path comes first. '' for a
    session that keeps none."""
    page = page_of_task(home, s)
    if not page:
        return ""
    return (f"phi (p4-phi): this session's context was compacted or cleared. Read its state page before anything "
            f"else, and resume from it: {page}")


# The app counts a session's context itself. The description of `mcp__ccd_session_mgmt__get_usage` gives `context`
# as "that session's window as the composer shows it — tokens used, percent, where auto-compact starts", "read from
# the session's own process". So p4-phi sums no usage row of a transcript and holds no window size: a line that turns
# on the share names that call on `"self"`, which the session makes while its own process runs.

def clear_at(store):
    """The percent of its context past which a session that keeps a state page clears itself: p4.json phi.clear_at
    when it is a number above 0 and at most 100, else CLEAR_AT."""
    at = _conf(store, "clear_at")
    return at if isinstance(at, (int, float)) and not isinstance(at, bool) and 0 < at <= 100 else CLEAR_AT


# A clear that resumes from a state page is p4's own rule. `/clear` starts one conversation over, sessions.md, "Manage
# context within a session": "start fresh with an empty context. Claude Code saves the previous session". The
# description of `mcp__ccd_session_mgmt__clear_session` takes one session a call, this one or "an idle session this
# session started", and refuses one "the user has pinned, has open on screen, or that still holds a queued message
# or other live work". No page and no tool clears a session together with the sessions it started, so the line below
# names each call, the coworkers' ahead of the session's own.

def idle_coworkers(home, s):
    """The live sessions `s` started itself that p4-phi's records hold idle with an empty queue and a state page to
    resume from: not inside a turn, no open plan step, no background task still running at its last turn's end, and
    no report `s` has not been handed yet. A queued message, a pin, a session open on ezexe's screen and a turn begun
    after this read are in none of p4-phi's records: the app's own refusal of the clear covers them."""
    sid = s["sessionId"]
    seen = s.get("reportsSeen") if isinstance(s.get("reportsSeen"), int) else 0
    unread = {r["sessionId"] for r in PHI.latest_reports(PHI.load_reports(home, sid)[seen:])}
    w = _watcher()
    return [k for k, ks in sorted(plans._children(home, sid).items())
            if page_of_task(home, ks) and k not in unread and not w.working(home, k)
            and not plans.open_steps(home, k) and not w.held_tasks(home, k)
            and (not ks.get("pageTold") or os.path.isfile(state_page(ks)))]   # told at a wrap_up: once it is written


def clear_line(home, s, store):
    """At a turn's `wrap_up`, for a session that keeps a state page: bring the page up to date, whatever its context
    reads, so a clear loses nothing; then read its context share with the app's `get_usage` on `"self"` and, past the
    share p4.json names, clear each coworker of `idle_coworkers` and itself, its own clear the turn's last call. With
    no page, keep_line's one line for a coworker of a session that keeps one, and '' for any other."""
    page = page_of_task(home, s)
    if not page:
        return keep_line(home, s)
    kids = idle_coworkers(home, s)
    whose = ", its own or one the session that started it makes," if PHI.spawned_from(s) else ""
    first = (f", then clear each coworker p4-phi's records hold idle with an empty queue, by "
             f"`mcp__ccd_session_mgmt__clear_session` on its id, whatever its own context reads, so the family resets "
             f"together: {', '.join(f'`{k}`' for k in kids)}. A coworker clear the app refuses leaves that coworker "
             f"as it is. After those, make" if kids else ", and make")
    return (f"phi (p4-phi): bring this session's state page up to date at {page} before this turn ends, so a clear"
            f"{whose} loses nothing. Then read its context with `mcp__ccd_session_mgmt__get_usage` on `\"self\"`. "
            f"Where it reads past {clear_at(store)} percent, send what the turn still owes{first} "
            f"`mcp__ccd_session_mgmt__clear_session` with `\"self\"` the last call of this turn; it resumes from the "
            f"page in its next turn. If the app refuses the clear of this session, try again at the next turn's end.")


def board_path(home, sid):
    return os.path.join(PHI.session_dir(home, sid), "board.md").replace("\\", "/")


def rule_text(home, s):
    archives, asks = ARCHIVES_UPKEEP if UPKEEP else ARCHIVES
    return RULE.format(cmd=PHI.commands(), board=board_path(home, s["sessionId"]),
                       restate=PHI.RESTATE, archives=archives, asks=asks)


def pair_text(s, store=""):
    """What a session is told once when a puppeteer comes to control it, and once when that control ends.
    Its own record keeps the puppeteer's id under `puppeteer`; the caller saves it."""
    pid, _ = puppeteer_of(s, store)
    held = s.get("puppeteer") if isinstance(s.get("puppeteer"), dict) else {}
    if pid and held.get("sessionId") != pid:
        s["puppeteer"] = {"sessionId": pid, "time": PHI.now()}
        return "phi (p4-phi): " + PAIR.format(title=full_title(pid), pid=pid, cmd=PHI.commands(),
                                              asks="" if UPKEEP else PAIR_ASKS)
    if not pid and held.get("sessionId"):
        s.pop("puppeteer", None)
        return "phi (p4-phi): " + PAIR_OVER.format(title=full_title(held["sessionId"]), pid=held["sessionId"])
    return ""


def publisher(home, s, store=""):
    """The sessionId of the one session that publishes the issues of this session's tree: the session nobody
    started at its top."""
    sid = str(s.get("sessionId") or "")
    chain = relay.above(home, sid) if sid else []
    return chain[-1] if chain else sid


def create_refused(home, s, store=""):
    """For a `gh issue create` in the session `s`: '' in the session that publishes for its tree, else the one line
    that refuses the call, naming the `Finding:` form and that session by full title. A session below it writes the
    line into its report."""
    sid = publisher(home, s, store)
    if sid == s["sessionId"]:
        return ""
    return (f"phi (p4-phi): this call is refused: no session publishes a new issue on its own, and `gh issue create` "
            f"runs only in the session that publishes for this session's tree, the session nobody started at its "
            f"top, \"{full_title(sid)}\" `{sid}`. Write the finding into this session's report as one line in this "
            f"form, which goes up unchanged: `{issues.FINDING_FORM}`.")


# --- sessions that come under control without a command ----------------------------------------------------------------

def started_by(sid):
    """The live sessions whose app record names `sid` as their parent session, among the app's newest records."""
    out, seen = [], set()
    for root in PHI.app_roots():
        import glob
        files = glob.glob(os.path.join(root, "*", "*", "local_*.json"))
        try:
            files.sort(key=os.path.getmtime, reverse=True)
        except OSError:
            pass
        for p in files[:RECENT]:
            d = PHI.read_json(p)
            if d.get("sessionId") and d["sessionId"] not in seen and PHI.spawned_from(d) == sid \
                    and not d.get("isArchived"):
                seen.add(d["sessionId"])
                out.append(d["sessionId"])
    return out


# --- reports by reference -----------------------------------------------------------------------------------------------

RAISE = re.compile(r"\b(?:faults?|failed|fails|failing|again|stall(?:ed|s)?|stuck|refused)\b", re.I)
LOWER = re.compile(r"\b(?:land(?:ed|ing|ings)?|relay(?:ed|s)?|pushed|rerun|reran|words-only|word commits?)\b", re.I)
EFFORT = {"raise": "raise, its report names faults from a check, a fix started again or a stall",
          "lower": "lower, its turn was routine relays, landings, word commits or reruns",
          "low": "low, it is shown done with nothing open"}


def effort_of(state, first):
    """`raise`, `lower` or `low` for a reporting session, read from its state and its report's first line; '' when
    neither calls for a change."""
    if state == "shown done":
        return "low"
    if RAISE.search(first or ""):
        return "raise"
    if LOWER.search(first or ""):
        return "lower"
    return ""


def effort_text(rows):
    """One line for the puppeteer, naming each reporting session whose work calls for another effort; '' for none."""
    told = [f"- \"{full_title(sid)}\" `{sid}`: {EFFORT[k]}." for sid, state, first in rows
            for k in [effort_of(state, first)] if k]
    if not told:
        return ""
    return (f"phi (p4-phi): set these sessions' effort with `mcp__ccd_session_mgmt__set_session_effort` before each "
            f"one's next turn, and log each change on the board with `{PHI.commands()} note \"<the change>\" --source "
            f"\"<its report>\" --kind effort`. Change a model only where effort alone does not fit, with "
            f"`mcp__ccd_session_mgmt__set_session_model`:\n" + "\n".join(told))


# --- the board ------------------------------------------------------------------------------------------------------------

def requests_for(s, home=""):
    """The open requests controlled sessions addressed to this puppeteer, read where they lie, not yet
    answered."""
    answered = s.get("requestAnswers") if isinstance(s.get("requestAnswers"), dict) else {}
    out, stores = [], []
    for e in controlled(s, home):
        if e.get("store") and e["store"] not in stores:
            stores.append(e["store"])
    for store in stores:
        for r in starts.open_rows(store):
            if r.get("to") == s["sessionId"] and r.get("id") not in answered:
                out.append({**r, "store": store})
    return out


def findings(s, home=""):
    """Each `Finding:` line of the kept reports of the sessions a puppeteer controls and of the sessions of
    their trees, as the session that reported it, that session's record and the line. Oldest first and each line once,
    under the session that reported it first, the deeper one when two did in the same minute, since a parent session
    passes its children's lines up unchanged."""
    rows = []
    for e in controlled(s, home):
        top, store = e["sessionId"], e.get("store") or ""
        every = relay._sessions(store) if store else {}
        chains = {k: PHI.chain_of(store, k) for k in every}
        for sid in sorted((k for k in every if k == top or top in chains[k]), key=lambda k: -len(chains[k])):
            for t in PHI.load_turns(store, sid):
                for line in issues.findings(f"{t.get('report') or ''}\n{t.get('said') or ''}"):
                    rows.append((str(t.get("time") or ""), sid, every[sid], line))
    out, seen = [], set()
    for _, sid, k, line in sorted(rows, key=lambda r: r[0]):
        if line not in seen:
            seen.add(line)
            out.append((sid, k, line))
    return out


def published(line, notes):
    """Whether a note of kind `published` names this `Finding:` line, so its issue exists and it leaves the board."""
    said = " ".join(re.sub(r"^\s*Finding:\s*", "", str(line or "")).split())
    return bool(said) and any(said in " ".join(PHI.clean(n.get("claim")).split())
                              for n in notes if PHI.clean(n.get("kind")) == "published")


def board(home, s):
    """Rewrites board.md when what it holds changed, and returns its path."""
    sid = s["sessionId"]
    notes = PHI.load_notes(home, sid)
    lines = [f"# Puppeteer board: \"{full_title(sid, s)}\" `{sid}`", "",
             "Rewritten by p4-phi's hooks and its `controls` command, never by hand.",
             f"What is not here is kept with `phi.py note`: `--kind decision` or `--kind waiting` puts it under Waiting "
             f"on, `--kind parked` under Parked, and any other kind under Notes.", "",
             "## Controlled sessions", ""]
    for e in controlled(s, home):
        k, store = e["sessionId"], e.get("store") or ""
        state, against = standing(store, k)
        when, first = last_report(store, k)
        lines.append(f"- \"{full_title(k)}\" `{k}`, store {store or 'unknown'}: {state}"
                     + (": " + "; ".join(against) if against else "") + "."
                     + (f" Last report {when}: {first}" if when else "")
                     + (f" Page: {page_of(store, k)}" if store else ""))
    if not controlled(s, home):
        lines.append("None yet.")

    def of_kind(kind):
        return [f"- {PHI.clean(n.get('claim'))} Source: {PHI.clean(n.get('source'))}. Kept {n.get('time', '')}."
                for n in notes if PHI.clean(n.get("kind")) == kind]
    lines += ["", "## Waiting on", ""] + (of_kind("decision") + of_kind("waiting") or ["Nothing."])
    asked = requests_for(s, home)
    answers = s.get("requestAnswers") if isinstance(s.get("requestAnswers"), dict) else {}
    lines += ["", "## Requests to this puppeteer", ""]
    lines += [f"- {r['id']} \"{r.get('title')}\" from \"{full_title(r.get('requester'))}\": open." for r in asked]
    lines += [f"- {rid} \"{a.get('title', '')}\": declined {a.get('time', '')}: {a.get('why', '')}"
              for rid, a in sorted(answers.items()) if isinstance(a, dict)]
    if not asked and not answers:
        lines.append("None.")
    import asks                                    # ezexe's own requests, a row each, on their page
    have = asks.rows(home, sid)
    if have:
        lines += ["", "## Ledger of requests", "",
                  f"{len(have)} request{'s' if len(have) != 1 else ''} to this puppeteer, each with the session that "
                  f"holds it and its state, whole on {asks.page_path(home, sid)}."]
    found = [f for f in findings(s, home) if not published(f[2], notes)]
    lines += ["", "## Findings", ""]
    if found:
        lines += ["The `Finding:` lines of the reports of the controlled sessions and of the sessions of their trees. "
                  "This puppeteer publishes each one that needs an issue, once it has checked the open issues and "
                  "the running sessions, records it with `phi.py note \"<the finding> as #N\" --kind published`, and places the "
                  "session that resolves it: the controlled session whose tree holds its files is sent it in one "
                  "SendMessage, and one no controlled session covers gets a new orchestrator.", ""]
    lines += [f"- \"{full_title(sid, k)}\" `{sid}`: {line}" for sid, k, line in found] or ["None."]
    lines += ["", "## Parked", ""] + (of_kind("parked") or ["Nothing."])
    rules = [x for x in s.get("rulesChanged") or [] if isinstance(x, dict)]
    lines += ["", "## Feedback and user memories ezexe changed during the run", ""]
    lines += [f"- {x.get('name')}, {x.get('time', '')}" for x in rules] or ["None."]
    if rules:
        lines.append(f"Each is whole in {PHI.p4conf.sub(home, 'memory').replace(chr(92), '/')}.")
    other = [f"- {PHI.clean(n.get('claim'))} Source: {PHI.clean(n.get('source'))}. Kept {n.get('time', '')}."
             for n in notes if PHI.clean(n.get("kind")) not in ("decision", "parked", "waiting")]
    lines += ["", "## Notes", ""] + (other or ["None."])
    text = "\n".join(lines) + "\n"
    path = board_path(home, sid)
    try:
        with open(path, encoding="utf-8") as f:
            same = f.read() == text
    except OSError:
        same = False
    if not same:
        PHI.write_atomic(path, text)
    return path


def rules_changed(s, text):
    """The feedback and user memories a `live_rules` text names as changed or added, kept for the board; the caller
    saves."""
    names = re.findall(r"(?m)^- memory ([\w.-]+):", str(text or "").split("Removed, no longer rules:")[0])
    if names:
        kept = [x for x in s.get("rulesChanged") or [] if isinstance(x, dict)]
        kept += [{"name": n, "time": PHI.now()} for n in dict.fromkeys(names)]
        s["rulesChanged"] = kept[-60:]


def controls_text(home, s):
    """Where each controlled session stands."""
    lines = []
    for e in controlled(s, home):
        state, against = standing(e.get("store") or "", e["sessionId"])
        lines.append(f"- \"{full_title(e['sessionId'])}\" `{e['sessionId']}`, store {e.get('store') or 'unknown'}: "
                     f"{state}" + (": " + "; ".join(against) if against else ""))
    if not lines:
        lines.append("no session is controlled yet: this session has started no orchestrator that is still live")
    lines.append(f"The board: {board_path(home, s['sessionId'])}")
    return "\n".join(lines)


def waited_on(s, home=""):
    """The full titles of the controlled sessions a puppeteer may still be waiting on: each one the app has
    not archived that is working, has something open, or is not shown done."""
    out = []
    for e in controlled(s, home):
        state, _ = standing(e.get("store") or "", e["sessionId"])
        if state in ("working", "open", "not shown done"):
            out.append(full_title(e["sessionId"]))
    return out


# --- a boundary, and its notice ------------------------------------------------------------------------------------------
#
# context-window.md, "When your context fills up": "Claude Code compacts automatically as you approach the limit, so a
# full context window doesn't end your session." So a boundary puts no compact question to ezexe and hands no line to
# type. What no compaction keeps for a puppeteer is what its board lacks, so the notice names `note` and nothing else.

def boundary(home, s):
    """The notice a puppeteer is handed once at each boundary, and an empty string otherwise: a boundary is
    a controlled tree that has closed, or every controlled session idle with no request waiting. Never while a
    controlled session waits on the puppeteer's answer. It says to keep what is not on the board with `note`, and
    asks nothing of ezexe. The caller saves what was told."""
    rows = controlled(s, home)
    if not rows or requests_for(s, home):
        return ""
    states, closed, ready = [], [], []
    for e in rows:
        state, against = standing(e.get("store") or "", e["sessionId"])
        when, _ = last_report(e.get("store") or "", e["sessionId"])
        states.append((e["sessionId"], state, when))
        if state == "archived":
            closed.append(e["sessionId"])
        elif state == "shown done" and not against:
            ready.append(e["sessionId"])
    told = s.get("boundary") if isinstance(s.get("boundary"), dict) else {}
    newly = [k for k in closed if k not in (told.get("closed") or [])]
    idle = all(st != "working" for _, st, _ in states)
    fresh = [k for k in ready if k not in (told.get("ready") or [])]
    if not newly and not idle and not fresh:
        return ""
    key = hashlib.sha1(json.dumps(sorted(states)).encode("utf-8")).hexdigest()[:12]
    if told.get("key") == key:
        return ""
    s["boundary"] = {"key": key, "closed": closed, "ready": ready, "time": PHI.now()}
    pick = complete_text(ready)
    if pick and not (newly or idle):
        return pick                                # a tree is complete while another works: no boundary yet
    why = (f"the tree of \"{full_title(newly[0])}\" has closed" if newly else
           "every controlled session is idle and no request is waiting")
    path = board_path(home, s["sessionId"])
    return ((pick + "\n\n" if pick else "") +
            f"phi (p4-phi): a boundary: {why}. When this turn's messages are sent, keep what is not yet on the "
            f"board, {path}, with `{PHI.commands()} note`. Claude Code compacts this session by itself as its "
            f"context fills, and the board's path is the first thing it is handed after that.")


# What tells a puppeteer, while it is idle, that a session it controls ended a turn.
# The SendMessage tool's own text: "To hear when a session ON THIS MACHINE finishes what it is doing, pass
# `notify_when_idle: true`", and cross-session-messaging.md, "Get a notice when another session goes idle": "Only
# the Claude in your main conversation can subscribe, and only to your sessions on this machine." Until p4-phi
# 0.11.136 this line handed that call for each controlled session that works. It was never served: a controlled
# session is one the desktop app runs, since _standing reads a session with no record of the app as unread, and the
# call serves a Claude session on this machine outside the app alone. Seen on 2026-11-22 in the desktop app on Claude
# Code 2.1.326, from two sessions: the call to another session of the app by its id answered success false with
# "Nothing was subscribed: notify_when_idle is only supported for Claude sessions on this machine in this release
# (not teammates, subagents, Remote Control or cloud sessions)", and with a message attached "no idle subscription
# was made". The same call to a scripted `claude -p` run answered "Subscribed", which upkeep.py builds on for a
# worker in the Terminal panel.
# So the line hands no call and says what does tell:
# - A controlled session this puppeteer started: the app's own note of that session's turn end begins a turn here.
# - One it did not start: nothing begins a turn here. A session's hooks module sends each turn's report to the
#   session that started it, phi.starter_cli, and to nobody where nobody started it, and p4-phi speaks only when a
#   hook of the puppeteer's own fires, so the report is handed beside its next message. With `phi.upkeep` on, the
#   sweep's schedule, which upkeep.sweep_acts hands while such a session is inside a turn, brings the puppeteer back
#   within the hour, and with it off nothing does.
TURN_END_WATCH = ("phi (p4-phi): what tells this session, while it is idle, that a session it controls ended a turn. "
                  "No idle notice can be asked of one: each is a session the desktop app runs, and `SendMessage` "
                  "with `notify_when_idle` answers for such a session that nothing was subscribed, since it serves "
                  "a Claude session on this machine outside the app alone. {parts}")
TOLD_BY_APP = "which this session started: the app's own note of its turn end begins a turn here."
TOLD_BY_NOTHING = ("which this session did not start: nothing begins a turn here when its turn ends, and its report "
                   "is handed beside this session's next message.")
COVERED = ("The sweep's schedule, which upkeep hands while one of them is inside a turn, brings this session back "
           "within the hour.")
NOT_COVERED = "With `phi.upkeep` off no schedule covers it either."


def started_here(home, s, e):
    """True where the puppeteer `s` itself started the controlled session of the row `e`, by that session's record."""
    kept = relay._session(e.get("store") or home, e["sessionId"])
    return relay._parent(kept) == s["sessionId"]


def idle_watch(home, s):
    """The line that tells a puppeteer what brings it back when a controlled session that works ends its turn, and an
    empty string where none is new: a session is named once for its stretch of work, and again once it works after
    a later report. It hands no call, since none serves a session the app runs. The caller saves what was told."""
    rows = controlled(s, home)
    told = s.get("idleWatch") if isinstance(s.get("idleWatch"), dict) else {}
    new, mine, others = {}, [], []
    for e in rows:
        sid, store = e["sessionId"], e.get("store") or ""
        if standing(store, sid)[0] != "working":
            continue
        when = last_report(store, sid)[0] or "-"
        if told.get(sid) != when:
            new[sid] = when
            (mine if started_here(home, s, e) else others).append(f"\"{full_title(sid)}\"")
    if not new:
        return ""
    s["idleWatch"] = {**{k: v for k, v in told.items() if any(e["sessionId"] == k for e in rows)}, **new}
    parts = ([", ".join(mine) + ", " + TOLD_BY_APP] if mine else []) + (
        [", ".join(others) + ", " + TOLD_BY_NOTHING + " " + (COVERED if UPKEEP else NOT_COVERED)] if others else [])
    return TURN_END_WATCH.format(parts=" ".join(parts))


def complete_text(ready):
    """The line naming the controlled sessions p4-phi's records hold complete, which no tool of the app tells, and
    an empty string when there are none. Archiving is the app's: it asks ezexe before the archive tool runs. Where
    the project turns `phi.upkeep` on, the line holds the archive call of each, which waits on nobody."""
    if not ready:
        return ""
    names = "; ".join(f"\"{full_title(sid)}\" `{sid}`" for sid in ready)
    head = (f"phi (p4-phi): p4-phi's records hold {'these sessions' if len(ready) != 1 else 'this session'} this "
            f"puppeteer controls complete, shown done with nothing open: {names}. Keep each outcome that is not on "
            f"the board yet with `{PHI.commands()} note`, then ")
    if UPKEEP:
        return (head + "archive each with `mcp__ccd_session_mgmt__archive_session` and its `session_id`, in this "
                       "turn: `phi.upkeep` is on in this project, which is ezexe's standing word for it, so the call "
                       "waits on nobody. Say in one line which were archived.")
    return (head + "tell ezexe. Archiving one is `mcp__ccd_session_mgmt__archive_session`, which the app puts to "
                   "ezexe on its approval card outside Auto mode and Bypass permissions mode.")


def compacted(home, s):
    """A puppeteer after a compaction, typed or automatic: its board's path comes first. hooks-guide.md,
    "Re-inject context after compaction": "Use a `SessionStart` hook with a `compact` matcher to re-inject critical
    context after every compaction." """
    return (f"phi (p4-phi): this session is a puppeteer and its context was compacted. Read its board "
            f"before anything else: {board(home, s)}")


# --- a successor ------------------------------------------------------------------------------------------------------------


# --- requests through the puppeteer ------------------------------------------------------------------------------

def request_call(r):
    """The exact start_session input for a request addressed to a puppeteer: a new orchestrator in
    the environment of the session that filed the request, in that project's own checkout, where it lands its
    tree's work, so `use_worktree` is false, as starts.use_worktree gives a new orchestrator. `wake_when_done`
    is true, which by the start tool's schema "also continues you if this session never gets its task some other
    way, such as a brief that is not sent", and is "not with own_initiative", so no card carries it."""
    project = os.path.dirname(os.path.dirname(os.path.abspath(r["store"]))).replace("\\", "/")
    bg = str(r.get("background") or "")
    if len(bg) < starts.BACKGROUND_MIN:
        bg = starts.background_of(r["store"], r["requester"], bg)
    brief = r["brief"]
    if not starts.ORCHESTRATOR.search(brief):
        brief += "\n\n" + starts.ORCHESTRATOR_BRIEF
    return plans.with_level({"initiation": "user_asked", "title": r["title"], "context": "fresh",
                             "use_worktree": starts.use_worktree(brief), "cwd": project, "background": bg,
                             "wake_when_done": True,
                             "prompt": brief + "\n\n" + starts.marker(r["id"], r["requester"])},
                            r["title"] + "\n" + r["brief"])     # a fresh start names its model and effort


def requests_text(home, s):
    """The requests addressed to this puppeteer, handed at a turn ezexe began: each with its exact call."""
    rows = requests_for(s, home)
    if not rows:
        return ""
    lines = [f"- {r['id']} \"{r['title']}\" from \"{full_title(r['requester'])}\" `{r['requester']}`: "
             f"`mcp__ccd_session__start_session` with "
             f"{json.dumps(request_call(r), ensure_ascii=False)}" for r in rows]
    return ("phi (p4-phi): controlled sessions ask this puppeteer for new orchestrators. This turn ezexe "
            "began. Each call passes `cwd`, and the start tool's text has `mcp__ccd_session__list_start_targets` "
            "list the valid names, so call that first, once: a folder it does not list is named to ezexe in one "
            "line and never guessed. For each either start it with exactly the call given, or decline "
            f"it with `{PHI.commands()} controls --decline <request id> \"<why>\"` and one line to ezexe. A started "
            "one stays attached under this session, which p4-phi reads as controlled:\n" + "\n".join(lines))


def decline(home, s, rid, why):
    row = next((r for r in requests_for(s, home) if r.get("id") == rid), None)
    if not row:
        raise ValueError(f"no open request {rid} is addressed to this puppeteer")
    if len(PHI.clean(why)) < REASON_MIN:
        raise ValueError("say why it is declined")
    answers = dict(s.get("requestAnswers") or {}) if isinstance(s.get("requestAnswers"), dict) else {}
    answers[rid] = {"declined": True, "why": PHI.cut(PHI.clean(why), 300), "time": PHI.now(),
                    "title": row.get("title"), "requester": row.get("requester")}
    s["requestAnswers"] = answers
    PHI.save_session(home, s)
    return f"declined {rid} \"{row.get('title')}\": the session that filed it is told at its next message"


def answers_text(home, s):
    """What became of a session's requests to its puppeteer, read from the puppeteer's record: a
    declined one is closed in this session's own store and named once."""
    mine = [r for r in starts.open_rows(home) if r.get("requester") == s["sessionId"] and r.get("to")]
    lines = []
    for r in mine:
        pstore = store_of(r["to"])
        p = PHI.load_session(pstore, r["to"]) if pstore else {}
        a = (p.get("requestAnswers") or {}).get(r["id"]) if isinstance(p.get("requestAnswers"), dict) else None
        if isinstance(a, dict) and a.get("declined"):
            starts.started(home, r["id"], "withdrawn")
            lines.append(f"its puppeteer \"{full_title(r['to'])}\" declined the request {r['id']} "
                         f"\"{r.get('title')}\": {a.get('why', '')}")
    return ("phi (p4-phi): " + "; ".join(lines) + ". Start no session for it.") if lines else ""


# --- work sent down to a controlled session --------------------------------------------------------------------------------

def route_down(s, words_, home=""):
    """The line that sends ezexe's message to a puppeteer on to the controlled session whose topic covers
    it, and an empty string when no controlled session's topic covers it."""
    best = covering(s, words_, home)
    if not best:
        return ""
    sid = best["sessionId"]
    return (f"phi (p4-phi): this message reads as work on the topic \"{full_title(sid)}\" `{sid}` orchestrates. If so, "
            f"do not do it here and start no child for it: send that session one message with SendMessage, holding "
            f"{PHI.RESTATE}, and telling it to brief and start a worker of its own for it. Keep it on the board with `{PHI.commands()} note \"<what was sent "
            f"and to whom>\" --source \"<the message>\" --kind waiting` until its report comes.")


def covering(s, words_, home=""):
    """The running session a puppeteer controls whose topic covers some words, as its row of `controls`, and None
    when none does: the live one whose full title and task share the most content words with them, SHARE at
    least."""
    said = plans.words(words_)
    best, score = None, SHARE - 1
    for e in controlled(s, home):
        store = e.get("store") or ""
        k = PHI.load_session(store, e["sessionId"]) if store else {}
        if out_of_tree(k) if k else True:
            continue
        n = len(said & (plans.words(full_title(e["sessionId"], k)) | plans.words(k.get("task"))))
        if n > score:
            best, score = e, n
    return best


# --- the open issues no session holds --------------------------------------------------------------------------------
#
# An open issue of a repository a controlled session works in is the puppeteer's to resolve and is no choice of
# ezexe's. The puppeteer's own watcher lists them from GitHub at its slow looks, puppeteer.list_open, and no hook
# reads GitHub for this: the line below reads the file that look keeps.

OPEN_SHOWN = 12                  # the issues one line names; the rest wait for the next tree that closes or reports done
OPEN_NAMED = 400                 # the issues a puppeteer was named, remembered so each is named once


def open_issues(home, s):
    """The open issues the puppeteer's watcher last listed that no live session's record holds as `issue`, each as
    its `owner/name` and its row of number and title, in the order listed."""
    w = _watcher()
    repos = relay._read_json(w.open_path(home, s["sessionId"])).get("repos")
    held = w.held_issues(home, s)
    return [(slug, x) for slug, row in (repos.items() if isinstance(repos, dict) else [])
            for x in (row.get("issues") if isinstance(row, dict) else None) or []
            if isinstance(x, dict) and str(x.get("number") or "").isdigit()
            and f"{slug.lower()}#{int(x['number'])}" not in held]


def open_issues_text(home, s):
    """The one line a puppeteer is handed when a controlled tree has closed or a controlled session has reported
    done: the open issues of the repositories its controlled sessions work in that no live session holds, each
    named once. Beside each stands the running orchestrator whose topic covers it, picked as route_down picks one
    for ezexe's words, so the puppeteer sends it straight there, or the start of a new orchestrator where none
    covers it. It tells the puppeteer to close what a landed commit covers and to route or start the rest, and puts
    none to ezexe. One line names OPEN_SHOWN at most. A tree that closed or a session that reported done while the
    watcher had listed nothing to name is counted when it has. '' with the issue loop off. The caller saves what
    was told."""
    if not issues.on(home):
        return ""
    told = s.get("openIssues") if isinstance(s.get("openIssues"), dict) else {}
    closed, done = [], {}
    for e in controlled(s, home):
        sid, store = e["sessionId"], e.get("store") or ""
        if PHI.app_record(sid).get("isArchived"):
            closed.append(sid)
            continue
        turns = PHI.load_turns(store, sid) if store else []
        if turns and turns[-1].get("done"):
            done[sid] = str(turns[-1].get("time") or "")
    was = told.get("done") if isinstance(told.get("done"), dict) else {}
    if not [k for k in closed if k not in (told.get("closed") or [])] \
            and not [k for k, when in done.items() if was.get(k) != when]:
        return ""
    named = [x for x in told.get("named") or [] if isinstance(x, str)]
    rows = [(slug, x) for slug, x in open_issues(home, s) if f"{slug.lower()}#{int(x['number'])}" not in named]
    if not rows:
        return ""
    more, rows, lines = len(rows) - OPEN_SHOWN, rows[:OPEN_SHOWN], []
    for slug, x in rows:
        n, title = int(x["number"]), PHI.clean(x.get("title"))
        e = covering(s, title, home)
        where = (f"send it to \"{full_title(e['sessionId'])}\" `{e['sessionId']}`, whose topic covers it" if e else
                 "no running orchestrator's topic covers it, so start a new orchestrator for it")
        lines.append(f"- {slug}#{n} \"{title}\", https://github.com/{slug}/issues/{n}: {where}")
        named.append(f"{slug.lower()}#{n}")
    s["openIssues"] = {"closed": closed, "done": done, "named": named[-OPEN_NAMED:]}
    return (f"phi (p4-phi): this session's watcher last listed {'this issue' if len(rows) == 1 else 'these issues'} "
            f"as open on the repositories the controlled sessions work in and held by no live session. An open issue "
            f"there is this puppeteer's to resolve, and none of them is a question for "
            f"ezexe. Close each one a landed commit already covers. Send each other one "
            f"straight to the orchestrator named beside it, in one SendMessage holding the issue's link and "
            f"{PHI.RESTATE}, and start a new orchestrator for each one that names none. Each is named here "
            f"once" + (f", and {more} more wait for the next tree that closes or reports done" if more > 0 else "")
            + ":\n" + "\n".join(lines))
