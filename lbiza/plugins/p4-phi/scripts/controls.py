"""controls.py: a puppeteer and the sessions it controls.

ezexe files an orchestrator in the sidebar section "puppeteers", which makes it a puppeteer: it controls
the top-level orchestrators of one or more environments, an environment being a project with its own store. The
sessions it controls are its controlled sessions, and each stays at the top of its own tree, in its own section.
The watcher every orchestrator has is puppeteer.py's and is another thing.

  the filing   p4-phi's hooks are command hooks, which call none of the app's tools, but the app keeps the sidebar
               on disk: claude_desktop_config.json, beside the claude-code-sessions folder, holds
               preferences.epitaxyPrefs["dframe-group-scopes"], each scope with `groups`, each group an `id` and a
               `name`, and `assignments`, which maps `code:<sessionId>` to a group id. p4-phi reads the filing there
               each time it matters and keeps no copy of its own. A file that is missing or shaped otherwise makes
               nobody a puppeteer. Unless phi.json turns `app_tools` off, the plugin's hooks module asks the app's own
               tools, and a session's section is read first from what they answered: phi.app_group, from `group` of
               `get_session` and `list_sessions`, and phi.section_id, from `list_sections` or `list_groups`. The file
               is read for a session they did not answer. Nothing stops a session from filing itself, since the app asks nobody:
               the rule rests on ezexe's filing, and p4-phi says once, in the session and on its record, that it
               saw the session there, and tells every session it lists which session controls it.
  the record   `controls` on the puppeteer's session.json lists the sessions it controls, each with the
               store its tree lives in. That session.json is where every orchestrator's is: the store of the
               folder it was opened in. A controlled session's own hook finds the puppeteer that lists it
               and keeps its id as `puppeteer` on its own record. Each side reads the other's store and neither
               writes into it.
  the board    <the puppeteer's folder>/board.md, rewritten by its hooks and the `controls` command: each
               controlled session in a line with the path of its page, the requests addressed to the
               puppeteer, the `Finding:` lines of the reports of the controlled trees, the feedback and user memories
               ezexe changed during the run and its notes by kind. After a compaction its path is the first thing the
               puppeteer is handed.
  findings     no session publishes a new issue on its own. A finding goes up in the reports of the session tree as one
               `Finding:` line, and the puppeteer that controls the tree places the session that resolves it, while
               one session publishes what needs an issue for every tree it controls: the issues coworker of its
               standing worker, that worker until such a coworker is on record, and the puppeteer until it has a
               worker. Where none controls the tree, its orchestrator does both. `publisher` names that session, and
               a `gh issue create` in any other session is refused with its title.
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
  archiving    the app asks ezexe before every archive call, by the ask rule the settings keeper writes on the
               archive tool, and the tool refuses a session with live background work. p4-phi only names the
               controlled sessions its records hold complete, which no tool of the app tells: no open plan step
               and no closing commit unpushed. Where a project turns `phi.upkeep` on, the keeper writes no such
               rule, the line that names a complete session holds its archive call, and no line leaves the
               archive to ezexe.
  requests    a controlled session that would start a new orchestrator writes `request ... --to-puppeteer`
               into its own store; the puppeteer's hooks read it there, and what became of it is kept on
               the puppeteer's record, where the hook of the session that filed it reads it.
  the tree     the app nests a session under the session that calls the start tool, and no tool moves it after, so a
               puppeteer starts only new orchestrators and its one standing worker. A worker of a controlled tree
               is that tree's own to start, as a start or as the suggested task card its session shows.
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

SECTION = "puppeteers"           # p4.json phi.puppeteer_section; "" turns the rule off
REASON_MIN = 12                  # characters of a reason that says something
RECENT = 120                     # the app's newest records looked through for sessions a puppeteer started
SHARE = 2                        # content words a message shares with a controlled session's topic to be sent there
_SECTIONS = {}                   # the app's file, read once a process: under "all", each session's section by its id
UPKEEP = False                   # phi.project_conf sets it from p4.json phi.upkeep


def _watcher():
    import puppeteer
    return puppeteer


def _conf(store, key):
    try:
        return p4conf.section(store, "phi", write=False).get(key) if store else None
    except Exception:  # noqa: BLE001
        return None


def section_name(store):
    """The section's name for this project: p4.json phi.puppeteer_section when it is a string, else the default."""
    name = _conf(store, "puppeteer_section")
    return name.strip() if isinstance(name, str) else SECTION


def sections():
    """Each session's sidebar section by its sessionId, as the app's own file assigns it."""
    if "all" in _SECTIONS:
        return _SECTIONS["all"]
    out = {}
    for root in PHI.app_roots():
        d = PHI.read_json(os.path.join(os.path.dirname(root.rstrip("/\\")), "claude_desktop_config.json"))
        scopes = d.get("preferences") if isinstance(d, dict) else None
        scopes = scopes.get("epitaxyPrefs") if isinstance(scopes, dict) else None
        scopes = scopes.get("dframe-group-scopes") if isinstance(scopes, dict) else None
        for scope in (scopes.values() if isinstance(scopes, dict) else []):
            given = scope.get("assignments") if isinstance(scope, dict) else None
            groups = scope.get("groups") if isinstance(scope, dict) else None
            names = {g.get("id"): g.get("name") for g in (groups if isinstance(groups, list) else [])
                     if isinstance(g, dict) and isinstance(g.get("name"), str)}
            for key, gid in (given.items() if isinstance(given, dict) else []):
                if isinstance(key, str) and key.startswith("code:") and gid in names:
                    out.setdefault(key[5:], names[gid])
        if out:
            break
    _SECTIONS["all"] = out
    return out


def section_of(sid):
    """The sidebar section a session is filed in, '' for none: as the app's own tools answered the hooks module,
    where they did, else as the app's file assigns it."""
    held = PHI.app_group(sid)
    return held["name"] if held is not None else sections().get(str(sid or ""), "")


def is_puppeteer(s, store=""):
    """True for a puppeteer: an orchestrator the app's file shows filed in the section."""
    sid = str(s.get("sessionId") or "") if isinstance(s, dict) else ""
    want = section_name(store).lower()
    return bool(want and sid and not PHI.spawned_from(s) and section_of(sid).strip().lower() == want)


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


def controlled(s):
    return [e for e in s.get("controls") or [] if isinstance(e, dict) and e.get("sessionId")]


def _set(s, rows):
    s["controls"], s["_controlsSet"] = rows, True


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
    "This session is a puppeteer: ezexe filed it in the sidebar section \"{section}\", so it controls the "
    "orchestrators of other trees, which stay at the top of their own trees as its siblings. Record them with "
    "`{cmd} controls <sessionId> ...`; `{cmd} controls` prints where each stands. Its board is {board}, and what "
    "p4-phi cannot see goes on it through `{cmd} note`. Its turns hold messages only: ezexe's, which it answers "
    "directly where it can, the decisions that are ezexe's, the archive calls, {archives}, "
    "and the start of each new orchestrator. The app continues it with a short note when a session it started ends a turn, and "
    "p4-phi hands it one line per controlled session's turn; it relays none of these to ezexe and acts only on what "
    "is ezexe's. Work ezexe gives it on a controlled session's topic goes straight to that orchestrator in one "
    "SendMessage holding {restate}, a `Files:` line and what done looks like, and that session briefs and starts a "
    "worker of its own for it. A topic none covers gets a new orchestrator that this session starts and files in "
    "its environment's section with `mcp__ccd_sidebar__move_sessions`, which takes the section's id as "
    "`mcp__ccd_sidebar__list_sections` or `mcp__ccd_sidebar__list_groups` answers it, never in \"{section}\". "
    "Every other task "
    "goes to its one standing worker, which it starts under itself with the line `{worker}` in the brief: archive "
    "checks, never the archiving, store record corrections, landing checks, counts, audits, and the issues that "
    "flow up, which the worker's issues coworker drafts and publishes, handing each number up for this session to "
    "record with `{cmd} note \"<the finding> as #N\" --source \"<the issue>\" --kind published`. Beside that worker "
    "it starts only new "
    "orchestrators, since the app nests a session under its starter for good. It checks the orchestrators and its "
    "own worker for stalls and context, and tunes "
    "their effort from their reports, with no one asking, by `mcp__ccd_session_mgmt__set_session_effort`, logging "
    "each change on its board. It changes a running session's model, by "
    "`mcp__ccd_session_mgmt__set_session_model`, only where effort alone does not fit that session's work and its "
    "context is worth keeping, and starts a new session otherwise. A `Finding:` line "
    "stays on its board until such a note holds its text. It shows ezexe a result in its reply as a short "
    "table or list, with the full page kept in the store's notes, and publishes no Artifact and sends no file "
    "unless ezexe asks.{asks}")
# The two places of RULE that word the archive: who answers for the call, and the sentence that ends the rule. With
# `phi.upkeep` on, the call is the upkeep line's and no sentence leaves it to ezexe.
ARCHIVES = ("which the app puts to ezexe on its approval card",
            " The app asks ezexe on its approval card before each archive call it makes.")
ARCHIVES_UPKEEP = ("which its upkeep line names for each finished, landed session it started", "")
PAIR_ASKS = " The app asks ezexe on its approval card before any archive call on its tree."
PAIR = (
    "This session is controlled by a puppeteer: \"{title}\" `{pid}`, which ezexe filed in the sidebar "
    "section \"{section}\", lists this one among the sessions it controls. This session stays at the top of its own "
    "tree, in its own section, and orchestrates that tree itself. That puppeteer is the one address for a decision "
    "of ezexe's authority, a press the app requires or an outcome ezexe should hear; a message about a file, an "
    "issue or a piece of work goes straight to the session that holds that file, owns that issue or started that "
    "work, as the address book names it, never through the puppeteer.{asks}")
PAIR_OVER = ("This session has left the control of its puppeteer: \"{title}\" `{pid}` dropped it from the "
             "sessions it controls, or left the sidebar section. This session starts its own new orchestrators.")
ASK = ("phi (p4-phi): this session is controlled by a puppeteer, so where a line here says to start a new "
       "orchestrator, start none: write `{cmd} request \"<title>\" --brief \"<the whole brief>\" --to-puppeteer`, "
       "the brief holding a line `Files: <paths>`. Its puppeteer \"{title}\" starts it or declines it with "
       "one line to ezexe.")


# --- the puppeteer's standing worker ----------------------------------------------------------------------------------
#
# A puppeteer's turns hold messages only. Every other task runs in one standing worker it starts under itself, which
# splits its task groups into standing coworkers. The worker's brief holds one line naming it, so the start is let
# through and a second is refused while the first is live.

WORKER_BRIEF = "Standing worker of its puppeteer"
WORKER_LINE = re.compile(r"(?m)^\s*Standing worker of its puppeteer\b")
ISSUES_BRIEF = "Issues coworker of its standing worker"      # the line of a coworker's brief that marks it on record
ISSUES_LINE = re.compile(r"(?m)^\s*Issues coworker of its standing worker\b")
CLEAR_AT = 60                    # percent of a session's context past which it clears itself and resumes from its page
HAND_UP = ("It hands {up} a page's path and its counts, never the page's text, and it never publishes a result as "
           "an Artifact or sends it as a file unless ezexe asks.")
STATE_PAGE = ("It keeps its task, its queue, its open items and the sessions it works with by id on a state page, "
              "{page}, rewritten at each turn's end, so it resumes from that page after a compaction or a clear.")
WORKER_FIRST = ("phi (p4-phi): this session is the standing worker of the puppeteer \"{title}\" `{pid}`. It does every "
                "task of that puppeteer's that is not a message: archive checks, corrections of store records, "
                "landing checks, counts, audits, and the issues that flow up, which its issues coworker drafts and "
                "publishes. In this turn, since the app refuses starts in a turn another session's message began, it "
                "starts a standing coworker for each group of its tasks, each brief with a line `Model and effort: "
                "<model> at <effort> effort` naming the smallest model the group needs: Opus for judging work such as "
                "issue writing, Sonnet for mechanical checks, Haiku for plain reads. The brief of the coworker that "
                "drafts and publishes the issues also holds the line `" + ISSUES_BRIEF + "`, which makes it the one "
                "session of the puppeteer's trees whose `gh issue create` runs; until one is on record that call "
                "runs here. Each coworker ends every turn "
                "with one message to it, and it ends each turn with one closing message to the puppeteer holding "
                "only what is ezexe's or what the puppeteer asked for. " + HAND_UP + " " + STATE_PAGE)
COWORKER_FIRST = ("phi (p4-phi): this session is a standing coworker of \"{title}\" `{pid}`, the standing worker of a "
                  "puppeteer. It ends every turn with one message to that worker. " + HAND_UP + " " + STATE_PAGE)
ISSUES_FIRST = (" Its brief makes it the issues coworker: the one session whose `gh issue create` runs for the trees "
                "that puppeteer controls. It checks each finding against the open issues and the running sessions, "
                "publishes the ones that need an issue, and hands each number up.")


def is_worker_brief(text):
    """True for a brief that holds the standing worker's line."""
    return bool(WORKER_LINE.search(str(text or "")))


def worker_of(s):
    """The sessionId of a puppeteer's standing worker, '' for none."""
    w = s.get("standingWorker")
    return w if isinstance(w, str) else ""


def live(sid):
    """True while the app holds a record of the session and has not archived it."""
    rec = PHI.app_record(sid)
    return bool(rec) and not rec.get("isArchived")


STATE_NAME = "state.md in its own scratchpad directory, the one the app names"


def state_page(s):
    """A standing session's state page: state.md in the app's scratchpad of its first turn, never under .claude,
    where every write asks ezexe."""
    pad = str(s.get("scratchpadDir") or "").rstrip("/")
    return f"{pad}/state.md" if pad else STATE_NAME


def start_refused(home, s, brief, store):
    """For a puppeteer's start of its standing worker: None to let it through, or the reason a second one is refused
    while the first is live. '' for any other start."""
    if not is_worker_brief(brief) or not is_puppeteer(s, store):
        return ""
    held = worker_of(s)
    if held and live(held):
        return (f"phi (p4-phi): this start is refused: this puppeteer's standing worker {link(held)} `{held}` is "
                f"live, and a puppeteer has one. Send it the work with SendMessage.")
    return None


def worker_first(home, s, prompt, store):
    """The standing worker's or a standing coworker's first message: what it is and how it hands up. It records the
    worker on its puppeteer's session, and a coworker whose brief holds ISSUES_BRIEF as the issues coworker, by
    `standingGroup` on its own record; the caller saves `s`. '' for any other session."""
    pid = PHI.spawned_from(s)
    if not pid:
        return ""
    up = PHI.load_session(home, pid)
    page = state_page(s)
    if is_worker_brief(prompt) and is_puppeteer(up, store):
        up["standingWorker"] = s["sessionId"]
        PHI.save_session(home, up)
        s["standingKind"] = "worker"
        return WORKER_FIRST.format(title=full_title(pid, up), pid=pid, page=page, up="its puppeteer")
    if up.get("standingKind") == "worker":
        s["standingKind"] = "coworker"
        said = COWORKER_FIRST.format(title=full_title(pid, up), pid=pid, page=page, up="that worker")
        if ISSUES_LINE.search(str(prompt or "")):
            s["standingGroup"] = "issues"
            said += ISSUES_FIRST
        return said
    return ""


def mark_puppeteer(home, cli):
    """A file named by the puppeteer's CLI session id, which the plugin's hooks module reads so each of its edits
    and shell calls reaches phi.py, not only the ones its filters pass."""
    name = PHI.SAFE.sub("_", str(cli or ""))[:80]
    if not home or not name:
        return
    path = os.path.join(home, "phi", ".puppeteers", name)
    if not os.path.exists(path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "a", encoding="utf-8").close()
        except OSError:
            pass


def tool_line(s, store):
    """A puppeteer's tool call that is no message: one line that sends the task to its standing worker. '' for any
    other session."""
    if not is_puppeteer(s, store):
        return ""
    held = worker_of(s)
    if held and live(held):
        return (f"phi (p4-phi): this session is a puppeteer and its turns hold messages only. Send this task to its "
                f"standing worker {link(held)} `{held}` in one SendMessage, with a `Files:` line and what done looks "
                f"like.")
    return (f"phi (p4-phi): this session is a puppeteer and its turns hold messages only. Start its standing worker "
            f"under itself, the brief holding the line `{WORKER_BRIEF}`, and send it this task.")


def usage_line(home, s, prompt, store, by=""):
    """A puppeteer, at a message carrying its standing worker's report: one line naming those of the worker and its
    coworkers whose context passed the line, for the puppeteer to name to the worker. Each one's share is Claude
    Code's last measure of it, which the plugin's hooks module keeps in usage.json in the session's folder and
    phi.usage_of reads, so no session is asked for it. A session with no measure kept, which no hooks module wrote
    for, is still named for one `get_usage` read. '' otherwise, and where every measure reads under the line.
    `by` is whose words the prompt is by its origin, rows.whose, and the sender is the one the message's wrapper
    names, rows.sender_of: a report the worker's hooks module sent names the worker as `from-session`, beside the
    socket it came over, and a message the worker's model sent names it as `from`."""
    held = worker_of(s)
    if not held or by not in ("", "session") or rows.sender_of(prompt) != held or not is_puppeteer(s, store):
        return ""
    every = relay._sessions(home)
    ids = [held] + sorted(k for k, v in every.items() if PHI.spawned_from(v) == held and live(k))
    at = clear_at(store)
    past, unmeasured = [], []
    for k in ids:
        kept = PHI.usage_of(home, k)
        share = (kept.get("context") or {}).get("percent")
        if not kept:
            unmeasured.append(k)
        elif share is not None and share >= at:    # a fresh window holds no share yet: nothing to clear
            past.append(f"`{k}` at {share:g} percent")
    if not past and not unmeasured:
        return ""
    clears = ("so that session brings its state page up to date and calls `mcp__ccd_session_mgmt__clear_session` "
              "with `\"self\"` at its turn's end")
    said = [f"phi (p4-phi): its standing worker `{held}` reported."]
    if past:
        said.append(f"By Claude Code's last measure of each, kept in its usage.json, the context of "
                    f"{', '.join(past)} passes {at:g} percent: send the worker one line naming "
                    f"{'it' if len(past) == 1 else 'them'}, {clears}.")
    if unmeasured:
        named = ', '.join(f'`{k}`' for k in unmeasured)
        said.append(f"No measure is kept of {named}: read `mcp__ccd_session_mgmt__get_usage` for each, and "
                    + (f"name in that line any whose context passes {at:g} percent." if past else
                       f"send the worker one line naming any whose context passes {at:g} percent, {clears}."))
    return " ".join(said)


STATE_IN_TASK = re.compile(r"\bState page:\s*(\S+?)[.,;]?(?=\s|$)")


def page_of_task(home, s):
    """The state page a session keeps: the one its p4-phi task names, else a standing worker's or coworker's own;
    '' for none."""
    m = STATE_IN_TASK.search(PHI.clean(s.get("task")))
    if m:
        return m.group(1).replace("\\", "/")
    if s.get("standingKind") in ("worker", "coworker") or s.get("pageTold"):
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
    return RULE.format(section=section_of(s["sessionId"]), cmd=PHI.commands(), board=board_path(home, s["sessionId"]),
                       restate=PHI.RESTATE, worker=WORKER_BRIEF, archives=archives, asks=asks)


def control(home, s, add=(), drop=()):
    """Records or drops the sessions a puppeteer controls, and returns the lines to print."""
    rows, out = controlled(s), []
    for sid in [PHI.safe_id(x) for x in drop]:
        if any(e["sessionId"] == sid for e in rows):
            rows = [e for e in rows if e["sessionId"] != sid]
            out.append(f"dropped from control: {sid}")
    for sid in [PHI.safe_id(x) for x in add]:
        if sid == s["sessionId"]:
            raise ValueError("a puppeteer does not control itself")
        if not PHI.app_record(sid):
            raise ValueError(f"the app holds no record of {sid}")
        store = store_of(sid)
        held = PHI.load_session(store, sid) if store else {}
        rec = PHI.app_record(sid)
        if PHI.spawned_from(held) if held.get("sessionId") else (PHI.spawned_from(rec)
                                                                 and not rec.get("lineageDetached")):
            raise ValueError(f"{sid} was started by another session: a puppeteer controls "
                             f"orchestrators, and a worker is reached through its orchestrator")
        if not any(e["sessionId"] == sid for e in rows):
            rows.append({"sessionId": sid, "store": store, "time": PHI.now()})
            out.append(f"controlled: \"{full_title(sid)}\" `{sid}`" + (f", store {store}" if store else ""))
    _set(s, rows)
    PHI.save_session(home, s)
    return out


def puppeteer_of(s, store=""):
    """The sessionId and store of the puppeteer that lists an orchestrator under `controls`, and two
    empty strings when none does."""
    sid = str(s.get("sessionId") or "") if isinstance(s, dict) else ""
    want = section_name(store).lower()
    if not want or not sid or PHI.spawned_from(s):
        return "", ""
    for pid, name in sorted(sections().items()):
        if pid == sid or name.strip().lower() != want:
            continue
        pstore = store_of(pid)
        p = PHI.load_session(pstore, pid) if pstore else {}
        if p.get("sessionId") and not PHI.spawned_from(p) and not p.get("handedTo") \
                and any(e["sessionId"] == sid for e in controlled(p)):
            return pid, pstore
    return "", ""


def pair_text(s, store=""):
    """What a session is told once when a puppeteer comes to control it, and once when that control ends.
    Its own record keeps the puppeteer's id under `puppeteer`; the caller saves it."""
    pid, _ = puppeteer_of(s, store)
    held = s.get("puppeteer") if isinstance(s.get("puppeteer"), dict) else {}
    if pid and held.get("sessionId") != pid:
        s["puppeteer"] = {"sessionId": pid, "time": PHI.now()}
        return "phi (p4-phi): " + PAIR.format(title=full_title(pid), pid=pid, section=section_of(pid),
                                              cmd=PHI.commands(), asks="" if UPKEEP else PAIR_ASKS)
    if not pid and held.get("sessionId"):
        s.pop("puppeteer", None)
        return "phi (p4-phi): " + PAIR_OVER.format(title=full_title(held["sessionId"]), pid=held["sessionId"])
    return ""


def ask_route(s):
    """In place of p4-phi's own way to a new orchestrator, for a session a puppeteer controls."""
    held = s.get("puppeteer") if isinstance(s.get("puppeteer"), dict) else {}
    if not held.get("sessionId"):
        return ""
    return (f"This session is controlled by a puppeteer, so it starts no new orchestrator itself: write "
            f"`{PHI.commands()} request \"<title>\" --brief \"<the whole brief>\" --to-puppeteer`, the brief holding "
            f"{PHI.RESTATE}. Its puppeteer "
            f"\"{full_title(held['sessionId'])}\" starts it as an orchestrator of this environment, files it in "
            f"this environment's section and takes it under control, or declines it with one line to ezexe.")


def ask_text(s):
    """The line that turns a controlled session's own start of a new orchestrator into a request."""
    held = s.get("puppeteer") if isinstance(s.get("puppeteer"), dict) else {}
    return ASK.format(cmd=PHI.commands(), title=full_title(held["sessionId"])) if held.get("sessionId") else ""


def issues_coworker(home, worker):
    """The live coworker of a standing worker whose brief marked it the issues coworker, the first started when
    there are two; '' for none."""
    marked = [(str(k.get("createdAt") or ""), sid) for sid, k in relay._sessions(home).items()
              if PHI.spawned_from(k) == worker and k.get("standingGroup") == "issues" and live(sid)]
    return min(marked)[1] if marked else ""


PUBLISHER = {"issues coworker": "the issues coworker of its puppeteer's standing worker",
             "standing worker": "its puppeteer's standing worker", "puppeteer": "its puppeteer",
             "": "the orchestrator of its tree"}


def publisher(home, s, store=""):
    """The session that publishes the issues a session's findings need, the one session of its tree whose
    `gh issue create` runs. Under a puppeteer, which is the top of the session's chain or controls it: the issues
    coworker of that puppeteer's standing worker once one is on record, else the standing worker, else the
    puppeteer. Under none: the orchestrator of its tree, which may be the session itself. Returns its sessionId,
    its full title, and what it is, a key of PUBLISHER: "issues coworker", "standing worker", "puppeteer", or ''
    for an orchestrator no puppeteer controls."""
    chain = PHI.chain_of(home, s["sessionId"])
    top = (PHI.load_session(home, chain[-1]) or {"sessionId": chain[-1]}) if chain else s
    pid, pstore = (top["sessionId"], home) if is_puppeteer(top, store) else puppeteer_of(top, store)
    if not pid:
        return top["sessionId"], full_title(top["sessionId"], top), ""
    p = top if pid == top["sessionId"] else PHI.load_session(pstore, pid)
    worker = worker_of(p)
    if worker and live(worker):
        co = issues_coworker(pstore, worker)
        return (co, full_title(co), "issues coworker") if co else (worker, full_title(worker), "standing worker")
    return pid, full_title(pid, p), "puppeteer"


def create_refused(home, s, store=""):
    """For a `gh issue create` in the session `s`: '' in the session that publishes for its tree, else the one line
    that refuses the call, naming the `Finding:` form and that session by full title. A session below it writes the
    line into its report; its puppeteer and its standing worker, which the reports go up to, send it the line."""
    sid, title, kind = publisher(home, s, store)
    if sid == s["sessionId"]:
        return ""
    who = PUBLISHER[kind]
    above = kind in ("issues coworker", "standing worker") and (is_puppeteer(s, store)
                                                              or s.get("standingKind") == "worker")
    if above:                                      # said of the session's own worker or coworker
        who = "its own issues coworker" if s.get("standingKind") == "worker" else who.replace("its puppeteer's", "its")
    how = ("Send that session the finding with SendMessage, as one line in this form" if above else
           "Write the finding into this session's report as one line in this form, which goes up unchanged")
    return (f"phi (p4-phi): this call is refused: no session publishes a new issue on its own, and `gh issue create` "
            f"runs only in the session that publishes for this session's tree, {who}, \"{title}\" `{sid}`. {how}: "
            f"`{issues.FINDING_FORM}`.")


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


def filing(store, s):
    """Where a new orchestrator of an environment is filed: the section its controlled siblings are in."""
    for e in controlled(s):
        if e.get("store") == store and section_of(e["sessionId"]):
            name = section_of(e["sessionId"])
            gid = PHI.section_id(name, e["sessionId"])     # known where the hooks module asked the app's tools
            return f"the section \"{name}\"" + (f" of the id `{gid}`" if gid else "")
    return "the ungrouped list under its project"


def take_started(home, s):
    """An orchestrator this puppeteer started is recorded as controlled, and the section to file it
    in is named."""
    rows, lines = controlled(s), []
    have = {e["sessionId"] for e in rows}
    for sid in started_by(s["sessionId"]):
        store = store_of(sid)
        k = PHI.load_session(store, sid) if store else {}
        if sid in have or not k.get("sessionId") or PHI.spawned_from(k):
            continue                               # not arrived yet, or a child of this puppeteer's own
        where = filing(store, s)
        rows.append({"sessionId": sid, "store": store, "time": PHI.now(), "started": True})
        have.add(sid)
        lines.append(f"\"{full_title(sid, k)}\" `{sid}` is an orchestrator this puppeteer started, so it "
                     f"is controlled. File it in {where} with `mcp__ccd_sidebar__move_sessions`, which takes the "
                     f"section's id as `mcp__ccd_sidebar__list_sections` or `mcp__ccd_sidebar__list_groups` answers "
                     f"it, never in \"{section_of(s['sessionId'])}\".")
    if lines:
        _set(s, rows)
    return lines


def announce(home, s):
    """An orchestrator ezexe started directly in a store where this puppeteer controls a session,
    named once. The app's own record decides it: a session whose record names the session that started it is a
    worker, even when its session.json was written before that record was read."""
    told, lines = [x for x in s.get("announced") or [] if isinstance(x, str)], []
    have = {e["sessionId"] for e in controlled(s)} | {s["sessionId"]}
    first = {}
    for e in controlled(s):
        if e.get("store"):
            first[e["store"]] = min(first.get(e["store"], "9"), str(e.get("time") or ""))
    for store, since in first.items():
        for sid, k in sorted(relay._sessions(store).items()):
            if sid in have or sid in told or PHI.spawned_from(k) or out_of_tree(k) \
                    or not sid.startswith("local_") or str(k.get("createdAt") or "") < since \
                    or is_puppeteer(k, store):
                continue
            rec = PHI.app_record(sid)
            if not rec or PHI.spawned_from(rec):   # no record yet, or one that names the session that started it
                continue
            told.append(sid)
            lines.append(f"\"{full_title(sid, k)}\" `{sid}` is a new orchestrator in {store} that this puppeteer "
                         f"does not control: `{PHI.commands()} controls {sid}` takes it under control.")
    if lines:
        s["announced"] = told[-200:]
    return lines


# --- reports by reference -----------------------------------------------------------------------------------------------

def reports(s, rows=None):
    """One line for each controlled session whose last turn ended since the puppeteer last looked, with
    its page's path, never the report's text. Each reporting session goes on `rows` too, as its sessionId, state
    and first line. The caller saves what was seen."""
    seen = dict(s.get("controlSeen") or {}) if isinstance(s.get("controlSeen"), dict) else {}
    lines = []
    for e in controlled(s):
        sid, store = e["sessionId"], e.get("store") or ""
        when, first = last_report(store, sid)
        if not when or seen.get(sid) == when:
            continue
        seen[sid] = when
        state, _ = standing(store, sid)
        if rows is not None:
            rows.append((sid, state, first))
        lines.append(f"- \"{full_title(sid)}\" `{sid}` ended a turn at {when}, {state}: {first} Its page: "
                     f"{page_of(store, sid)}")
    if lines:
        s["controlSeen"] = seen
    return lines


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

def requests_for(s):
    """The open requests controlled sessions addressed to this puppeteer, read where they lie, not yet
    answered."""
    answered = s.get("requestAnswers") if isinstance(s.get("requestAnswers"), dict) else {}
    out, stores = [], []
    for e in controlled(s):
        if e.get("store") and e["store"] not in stores:
            stores.append(e["store"])
    for store in stores:
        for r in starts.open_rows(store):
            if r.get("to") == s["sessionId"] and r.get("id") not in answered:
                out.append({**r, "store": store})
    return out


def findings(s):
    """Each `Finding:` line of the kept reports of the sessions a puppeteer controls and of the sessions of
    their trees, as the session that reported it, that session's record and the line. Oldest first and each line once,
    under the session that reported it first, the deeper one when two did in the same minute, since a parent session
    passes its children's lines up unchanged."""
    rows = []
    for e in controlled(s):
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
    for e in controlled(s):
        k, store = e["sessionId"], e.get("store") or ""
        state, against = standing(store, k)
        when, first = last_report(store, k)
        lines.append(f"- \"{full_title(k)}\" `{k}`, store {store or 'unknown'}: {state}"
                     + (": " + "; ".join(against) if against else "") + "."
                     + (f" Last report {when}: {first}" if when else "")
                     + (f" Page: {page_of(store, k)}" if store else ""))
    if not controlled(s):
        lines.append("None yet.")

    def of_kind(kind):
        return [f"- {PHI.clean(n.get('claim'))} Source: {PHI.clean(n.get('source'))}. Kept {n.get('time', '')}."
                for n in notes if PHI.clean(n.get("kind")) == kind]
    lines += ["", "## Waiting on", ""] + (of_kind("decision") + of_kind("waiting") or ["Nothing."])
    asked = requests_for(s)
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
    found = [f for f in findings(s) if not published(f[2], notes)]
    lines += ["", "## Findings", ""]
    if found:
        lines += ["The `Finding:` lines of the reports of the controlled sessions and of the sessions of their trees. "
                  "The issues coworker of this puppeteer's standing worker publishes each one that needs an issue, "
                  "once it has checked the open issues and the running sessions, and hands its number up; this "
                  "puppeteer records it with `phi.py note \"<the finding> as #N\" --kind published`, and places the "
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
    for e in controlled(s):
        state, against = standing(e.get("store") or "", e["sessionId"])
        lines.append(f"- \"{full_title(e['sessionId'])}\" `{e['sessionId']}`, store {e.get('store') or 'unknown'}: "
                     f"{state}" + (": " + "; ".join(against) if against else ""))
    if not lines:
        lines.append("no session is controlled yet: `controls <sessionId> ...` records the orchestrators ezexe "
                     "put under this one")
    if s.get("puppeteerSeen"):
        lines.append(f"p4-phi first saw this session in the section at {s['puppeteerSeen']}.")
    lines.append(f"The board: {board_path(home, s['sessionId'])}")
    return "\n".join(lines)


def waited_on(s):
    """The full titles of the controlled sessions a puppeteer may still be waiting on: each one the app has
    not archived that is working, has something open, or is not shown done."""
    out = []
    for e in controlled(s):
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
    rows = controlled(s)
    if not rows or requests_for(s):
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
    rows = controlled(s)
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
    return (head + "tell ezexe. Archiving one is "
                   "`mcp__ccd_session_mgmt__archive_session`, which the app puts to ezexe on its approval card.")


def compacted(home, s):
    """A puppeteer after a compaction, typed or automatic: its board's path comes first. hooks-guide.md,
    "Re-inject context after compaction": "Use a `SessionStart` hook with a `compact` matcher to re-inject critical
    context after every compaction." """
    return (f"phi (p4-phi): this session is a puppeteer and its context was compacted. Read its board "
            f"before anything else: {board(home, s)}")


# --- a successor ------------------------------------------------------------------------------------------------------------

def hand(home, s, new):
    """The old puppeteer marks its hand-over to a successor."""
    new = PHI.safe_id(new)
    if new == s["sessionId"] or not PHI.app_record(new):
        raise ValueError(f"the app holds no record of a successor {new}")
    s["handedTo"] = {"sessionId": new, "time": PHI.now()}
    PHI.save_session(home, s)
    return (f"handed over to \"{full_title(new)}\" `{new}`: it runs `controls --from {s['sessionId']}`, then keeps "
            f"this session's outcome with `note`, and "
            + ("its upkeep line names this session's archive call once it is finished and landed" if UPKEEP else
               "the app asks ezexe on its approval card before it archives this session"))


def take(home, s, old):
    """The successor takes over the old puppeteer's controlled sessions and its notes."""
    old = PHI.safe_id(old)
    ostore = store_of(old)
    o = PHI.load_session(ostore, old) if ostore else {}
    if (o.get("handedTo") or {}).get("sessionId") != s["sessionId"]:
        raise ValueError(f"{old} has not handed over to this session: it runs `controls --hand {s['sessionId']}` "
                         f"first")
    rows = controlled(s)
    have = {e["sessionId"] for e in rows}
    rows += [e for e in controlled(o) if e["sessionId"] not in have and e["sessionId"] != s["sessionId"]]
    s["handedFrom"] = {"sessionId": old, "time": PHI.now()}
    for k in ("rulesChanged", "requestAnswers"):
        if o.get(k) and not s.get(k):
            s[k] = o[k]
    _set(s, rows)
    PHI.save_session(home, s)
    n = 0
    for note in PHI.load_notes(ostore, old):
        try:
            n += bool(PHI.note_add(home, s["sessionId"], note.get("claim"),
                                   note.get("source") or f"handed over from {old}", note.get("kind") or ""))
        except ValueError:
            pass
    return (f"took over {len(rows)} controlled session{'s' if len(rows) != 1 else ''} and {n} note"
            f"{'s' if n != 1 else ''} from \"{full_title(old, o)}\" `{old}`")


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
    if not PHI.NEW_TOP.search(brief):
        brief += "\n\n" + PHI.NEW_TOP_BRIEF + " " + PHI.new_top_first_act()
    return plans.with_level({"initiation": "user_asked", "title": r["title"], "context": "fresh",
                             "use_worktree": starts.use_worktree(brief), "cwd": project, "background": bg,
                             "wake_when_done": True,
                             "prompt": brief + "\n\n" + starts.marker(r["id"], r["requester"])},
                            r["title"] + "\n" + r["brief"])     # a fresh start names its model and effort


def requests_text(home, s):
    """The requests addressed to this puppeteer, handed at a turn ezexe began: each with its exact call."""
    rows = requests_for(s)
    if not rows:
        return ""
    lines = [f"- {r['id']} \"{r['title']}\" from \"{full_title(r['requester'])}\" `{r['requester']}`, to be filed in "
             f"{filing(r['store'], s)}: `mcp__ccd_session__start_session` with "
             f"{json.dumps(request_call(r), ensure_ascii=False)}" for r in rows]
    return ("phi (p4-phi): controlled sessions ask this puppeteer for new orchestrators. This turn ezexe "
            "began. Each call passes `cwd`, and the start tool's text has `mcp__ccd_session__list_start_targets` "
            "list the valid names, so call that first, once: a folder it does not list is named to ezexe in one "
            "line and never guessed. For each either start it with exactly the call given and then file it with "
            "`mcp__ccd_sidebar__move_sessions` where named, which takes the section's id as "
            "`mcp__ccd_sidebar__list_sections` or `mcp__ccd_sidebar__list_groups` answers it, never in the section "
            "this session is filed in, or decline "
            f"it with `{PHI.commands()} controls --decline <request id> \"<why>\"` and one line to ezexe. p4-phi "
            "records a started one as controlled at this session's next hook:\n" + "\n".join(lines))


def decline(home, s, rid, why):
    row = next((r for r in requests_for(s) if r.get("id") == rid), None)
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

def route_down(s, words_):
    """The line that sends ezexe's message to a puppeteer on to the controlled session whose topic covers
    it, and an empty string when no controlled session's topic covers it."""
    best = covering(s, words_)
    if not best:
        return ""
    sid = best["sessionId"]
    return (f"phi (p4-phi): this message reads as work on the topic \"{full_title(sid)}\" `{sid}` orchestrates. If so, "
            f"do not do it here and start no child for it: send that session one message with SendMessage, holding "
            f"{PHI.RESTATE}, and telling it to brief and start a worker of its own for it. Keep it on the board with `{PHI.commands()} note \"<what was sent "
            f"and to whom>\" --source \"<the message>\" --kind waiting` until its report comes.")


def covering(s, words_):
    """The running session a puppeteer controls whose topic covers some words, as its row of `controls`, and None
    when none does: the live one whose full title and task share the most content words with them, SHARE at
    least."""
    said = plans.words(words_)
    best, score = None, SHARE - 1
    for e in controlled(s):
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
    for e in controlled(s):
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
        e = covering(s, title)
        where = (f"send it to \"{full_title(e['sessionId'])}\" `{e['sessionId']}`, whose topic covers it" if e else
                 "no running orchestrator's topic covers it, so start a new orchestrator for it")
        lines.append(f"- {slug}#{n} \"{title}\", https://github.com/{slug}/issues/{n}: {where}")
        named.append(f"{slug.lower()}#{n}")
    s["openIssues"] = {"closed": closed, "done": done, "named": named[-OPEN_NAMED:]}
    return (f"phi (p4-phi): this session's watcher last listed {'this issue' if len(rows) == 1 else 'these issues'} "
            f"as open on the repositories the controlled sessions work in and held by no live session. An open issue "
            f"there is this puppeteer's to resolve, and none of them is a question for "
            f"ezexe. Have its standing worker close each one a landed commit already covers. Send each other one "
            f"straight to the orchestrator named beside it, in one SendMessage holding the issue's link and "
            f"{PHI.RESTATE}, and start a new orchestrator for each one that names none. Each is named here "
            f"once" + (f", and {more} more wait for the next tree that closes or reports done" if more > 0 else "")
            + ":\n" + "\n".join(lines))
