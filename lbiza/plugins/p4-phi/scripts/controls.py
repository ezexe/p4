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
               nobody a puppeteer. Nothing stops a session from filing itself, since the app asks nobody:
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
               ezexe changed during the run, its notes by kind, and the archive calls let through or refused. After a
               compaction its path is the first thing the puppeteer is handed.
  findings     no session publishes a new issue on its own. A finding goes up in the reports of the session tree as one
               `Finding:` line, and the puppeteer that controls the tree publishes what needs an issue and
               places the session that resolves it; where none controls the tree, its orchestrator does.
  a boundary   a controlled tree has closed, or every controlled session is idle with no request waiting. The
               puppeteer is told once to end its turn on a question with two buttons. p4-phi speaks only
               when one of its hooks fires, so a boundary reached while the puppeteer is idle is told
               beside its next message: a command hook with `asyncRewake` could wake it at once, `SendMessage` with
               `notify_when_idle` could tell it when a controlled session goes idle, and p4-phi uses neither.
  archiving    a puppeteer archives only what ezexe picks. A complete controlled session is offered to
               ezexe, as a button on the turn's wrap-up when it is the one complete session while another still
               works, and otherwise as an option of its own by full title, at most four options to a multiple-choice
               question and four questions to one AskUserQuestion; the archive hook lets through only what ezexe
               picked in that turn. The completeness checks decide what is offered.
  requests     a controlled session that would start a new orchestrator writes `request ... --to-puppeteer`
               into its own store; the puppeteer's hooks read it there, and what became of it is kept on
               the puppeteer's record, where the hook of the session that filed it reads it.
  the tree     the app nests a session under the session that calls the start tool, and no tool moves it after, so a
               puppeteer starts only new orchestrators. A start request belongs under the session that
               filed it: each session of the controlled trees that holds some is named to the puppeteer as
               a link with how many it holds, beside its messages and on its board, for ezexe to open and press the
               button that session waits on. A start it makes on such a session's behalf anyway is held under that
               session in p4-phi, named to it for detaching to top level, and kept on its board as an exception.
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
import starts

PHI = None                       # phi.py's own module, handed over when phi.py imports this one

SECTION = "puppeteers"           # p4.json phi.puppeteer_section; "" turns the rule off
CHARS = 200000                   # p4.json phi.puppeteer_chars: once p4-phi has handed a puppeteer this many
#                                  characters since its last compaction, its boundary notice says so, and each further
#                                  multiple gives that notice again while a boundary holds
COMPACTIONS = 3                  # after this many, the notice offers a successor in place of "Later"
KEPT = 100                       # archive calls kept on a puppeteer's record
REASON_MIN = 12                  # characters of a reason that says something
RECENT = 120                     # the app's newest records looked through for sessions a puppeteer started
SHARE = 2                        # content words a message shares with a controlled session's topic to be sent there
_SECTIONS = {}                   # the app's file, read once a process: under "all", each session's section by its id


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


def ceiling(store):
    n = _conf(store, "puppeteer_chars")
    return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else CHARS


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
    return sections().get(str(sid or ""), "")


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

def waiting_requests(store, sid):
    """The start requests a session filed for itself that no turn of ezexe's in it has started yet."""
    return [r for r in starts.open_rows(store) if r.get("requester") == sid and not r.get("to")] if store else []


def standing(store, sid):
    """Where a controlled session stands, read from the app's record and its own store and written nowhere. Returns
    its state, one of archived, unread, working, open, shown done and not shown done, and the list of what p4-phi's
    records hold against archiving it."""
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
    if steps and not issues_closed(s, commits):    # once its issues are closed, a stale step holds nothing
        against.append(f"{len(steps)} open plan step{'s' if len(steps) != 1 else ''}, the next "
                       f"\"{PHI.cut(PHI.clean(steps[0].get('content')), 80)}\"")
    tasks = _watcher().held_tasks(store, sid)
    if tasks:
        against.append(f"{len(tasks)} background task{'s' if len(tasks) != 1 else ''} with no end recorded: "
                       + "; ".join(tasks[:3]))
    for kid, k in sorted(relay._sessions(store).items()):
        if kid == sid or out_of_tree(k) or sid not in PHI.chain_of(store, kid):
            continue
        if _watcher().working(store, kid) or plans.open_steps(store, kid):
            against.append(f"\"{full_title(kid, k)}\" under it is still working")
    asked = waiting_requests(store, sid)
    if asked:
        against.append(f"{len(asked)} start request{'s' if len(asked) != 1 else ''} of its own waiting, the first "
                       f"\"{asked[0].get('title')}\", which it starts at a turn ezexe begins there: ezexe opens "
                       f"{link(sid)} and presses the button its turn ended on")
    for path, sha, _, closes in commits:
        try:
            if not issues.landed(path, sha, closes):
                against.append(f"commit {sha}, which closes {', '.join(closes)}, is on no remote branch, and no "
                               f"commit there closes the same issue or carries the same change")
        except Exception:  # noqa: BLE001
            pass
    turns = PHI.load_turns(store, sid)
    every = plans.load(store, sid).get("steps") or []
    shown = bool(turns and turns[-1].get("done")) or bool(every) and not steps
    return ("working" if working else "open" if against else "shown done" if shown else "not shown done"), against


def issues_closed(s, commits):
    """True when a session names issues, by its own issue or its closing commits, and GitHub shows each closed."""
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
    return bool(named) and all(issues.issue_state(slug, n) == "CLOSED" for slug, n in sorted(named))


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
    "directly where it can, the decisions that are ezexe's, the archive calls on ezexe's picks and the start of "
    "each new orchestrator. The app continues it with a short note when a session it started ends a turn, and "
    "p4-phi hands it one line per controlled session's turn; it relays none of these to ezexe and acts only on what "
    "is ezexe's. Work ezexe gives it on a controlled session's topic goes straight to that orchestrator in one "
    "SendMessage holding {restate}, a `Files:` line and what done looks like, and that session briefs and starts a "
    "worker of its own for it. A topic none covers gets a new orchestrator that this session starts and files in "
    "its environment's section with `mcp__ccd_sidebar__move_sessions`, never in \"{section}\". Every other task "
    "goes to its one standing worker, which it starts under itself with the line `{worker}` in the brief: archive "
    "checks, never the archiving, store record corrections, landing checks, counts, audits, and the issues that "
    "flow up, which the worker's issues coworker drafts and publishes, handing each number up for this session to "
    "record with `{cmd} note \"<the finding> as #N\" --source \"<the issue>\" --kind published`. Beside that worker "
    "it starts only new "
    "orchestrators, since the app nests a session under its starter for good, and names a session holding a start "
    "request to ezexe as a link. It checks the orchestrators and its own worker for stalls and context, and tunes "
    "their effort from their reports, with no one asking, by `mcp__ccd_session_mgmt__set_session_effort`, logging "
    "each change on its board; a model is passed only on the start call and never changed after. A `Finding:` line "
    "stays on its board until such a note holds its text. It shows ezexe a result in its reply as a short "
    "table or list, with the full page kept in the store's notes, and publishes no Artifact and sends no file "
    "unless ezexe asks. It archives a session only on ezexe's pick, by the button or the multiple-choice question "
    "p4-phi hands it.")
PAIR = (
    "This session is controlled by a puppeteer: \"{title}\" `{pid}`, which ezexe filed in the sidebar "
    "section \"{section}\", lists this one among the sessions it controls. This session stays at the top of its own "
    "tree, in its own section, and orchestrates that tree itself. Its tree is archived only on ezexe's pick, "
    "by the button or the multiple-choice question p4-phi hands it at its end.")
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
                "issue writing, Sonnet for mechanical checks, Haiku for plain reads. Each coworker ends every turn "
                "with one message to it, and it ends each turn with one closing message to the puppeteer holding "
                "only what is ezexe's or what the puppeteer asked for. " + HAND_UP + " " + STATE_PAGE)
COWORKER_FIRST = ("phi (p4-phi): this session is a standing coworker of \"{title}\" `{pid}`, the standing worker of a "
                  "puppeteer. It ends every turn with one message to that worker. " + HAND_UP + " " + STATE_PAGE)


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


def state_page(home, sid):
    return os.path.join(PHI.session_dir(home, sid), "state.md").replace("\\", "/")


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
    worker on its puppeteer's session; the caller saves `s`. '' for any other session."""
    pid = PHI.spawned_from(s)
    if not pid:
        return ""
    up = PHI.load_session(home, pid)
    page = state_page(home, s["sessionId"])
    if is_worker_brief(prompt) and is_puppeteer(up, store):
        up["standingWorker"] = s["sessionId"]
        PHI.save_session(home, up)
        s["standingKind"] = "worker"
        return WORKER_FIRST.format(title=full_title(pid, up), pid=pid, page=page, up="its puppeteer")
    if up.get("standingKind") == "worker":
        s["standingKind"] = "coworker"
        return COWORKER_FIRST.format(title=full_title(pid, up), pid=pid, page=page, up="that worker")
    return ""


def mark_puppeteer(home, cli):
    """A file named by the puppeteer's CLI session id, which `recall-hook.sh lookup-check` reads so each of its tool
    calls reaches phi.py, not only the ones its gate lists."""
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


def usage_line(home, s, prompt, store):
    """A puppeteer, at a message carrying its standing worker's report: one line naming the worker and each of its
    coworkers, to read each one's context and tell the worker which passed the line. '' otherwise."""
    held = worker_of(s)
    if not held or f'<cross-session-message from="{held}"' not in str(prompt or "") or not is_puppeteer(s, store):
        return ""
    every = relay._sessions(home)
    ids = [held] + sorted(k for k, v in every.items() if PHI.spawned_from(v) == held and live(k))
    return (f"phi (p4-phi): its standing worker `{held}` reported. Read `mcp__ccd_session_mgmt__get_usage` for each "
            f"of {', '.join(f'`{k}`' for k in ids)}, and send the worker one line naming any whose context passes "
            f"{CLEAR_AT} percent, so that session brings its state page up to date and calls "
            f"`mcp__ccd_session_mgmt__clear_session` with `\"self\"` at its turn's end.")


STATE_IN_TASK = re.compile(r"\bState page:\s*(\S+?)[.,;]?(?=\s|$)")
WINDOW = 200000                  # p4.json phi.context_window: the tokens of a session's context window


def page_of_task(home, s):
    """The state page a session keeps: the one its p4-phi task names, else a standing worker's or coworker's own;
    '' for none."""
    m = STATE_IN_TASK.search(PHI.clean(s.get("task")))
    if m:
        return m.group(1).replace("\\", "/")
    if s.get("standingKind") in ("worker", "coworker"):
        return state_page(home, s["sessionId"])
    return ""


def state_first(home, s):
    """A session that keeps a state page, after a compaction or a clear: that page's path comes first. '' for a
    session that keeps none."""
    page = page_of_task(home, s)
    if not page:
        return ""
    return (f"phi (p4-phi): this session's context was compacted or cleared. Read its state page before anything "
            f"else, and resume from it: {page}")


def context_used(transcript):
    """The tokens of the context of a transcript's last assistant call: its input, cache creation and cache read
    together, from that row's `message.usage`; 0 when none is read."""
    try:
        with open(transcript, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400000))
            rows = f.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError, ValueError):
        return 0
    for line in reversed(rows):
        if '"usage"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        u = (d.get("message") or {}).get("usage") if isinstance(d.get("message"), dict) else None
        if d.get("type") == "assistant" and isinstance(u, dict):
            return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                     "cache_read_input_tokens"))
    return 0


def clear_line(home, s, transcript, store):
    """At a turn's `wrap_up`: past the share of its window p4.json names, a session that keeps a state page is told
    to bring it up to date and clear itself as the turn's last call. '' below the line or with no page."""
    page = page_of_task(home, s)
    if not page:
        return ""
    window, at = _conf(store, "context_window"), _conf(store, "clear_at")
    window = window if isinstance(window, int) and not isinstance(window, bool) and window > 0 else WINDOW
    at = at if isinstance(at, (int, float)) and not isinstance(at, bool) and 0 < at <= 100 else CLEAR_AT
    used = context_used(transcript)
    if used * 100 < at * window:
        return ""
    kids = sorted(k for k, v in relay._sessions(home).items() if PHI.spawned_from(v) == s["sessionId"] and live(k))
    first = (f" Before that, clear each of its coworkers that is idle with an empty queue, by "
             f"`mcp__ccd_session_mgmt__clear_session` on its id, whatever its own context reads, so the family resets "
             f"together: {', '.join(f'`{k}`' for k in kids)}." if kids else "")
    return (f"phi (p4-phi): this session's context is at {used * 100 // window} percent, past the line of {at} "
            f"percent. Bring its state page up to date at {page}, send what the turn still owes, and make "
            f"`mcp__ccd_session_mgmt__clear_session` with `\"self\"` the last call of this turn; it resumes from the "
            f"page in its next turn.{first} If the app refuses the clear, try again at the next turn's end.")


def board_path(home, sid):
    return os.path.join(PHI.session_dir(home, sid), "board.md").replace("\\", "/")


def rule_text(home, s):
    return RULE.format(section=section_of(s["sessionId"]), cmd=PHI.commands(), board=board_path(home, s["sessionId"]),
                       restate=PHI.RESTATE, worker=WORKER_BRIEF)


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
                                              cmd=PHI.commands())
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


def publisher(home, s, store=""):
    """The session that publishes the issues a session's findings need: the puppeteer that controls the
    orchestrator of its tree, else that orchestrator, which may be the session itself. Returns its
    sessionId, its full title, and whether it is a puppeteer."""
    chain = PHI.chain_of(home, s["sessionId"])
    top = (PHI.load_session(home, chain[-1]) or {"sessionId": chain[-1]}) if chain else s
    pid = top["sessionId"] if is_puppeteer(top, store) else puppeteer_of(top, store)[0]
    sid = pid or top["sessionId"]
    return sid, full_title(sid, top if sid == top["sessionId"] else None), bool(pid)


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
            return f"the section \"{section_of(e['sessionId'])}\""
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
                     f"is controlled. File it in {where} with `mcp__ccd_sidebar__move_sessions`, never in "
                     f"\"{section_of(s['sessionId'])}\".")
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
MODEL_FIXED = ("phi (p4-phi): a session's model was chosen at its start, from its work and the plan limits, and is "
               "not changed after, since a change mid-run re-prices its turns. Tune its effort with "
               "`mcp__ccd_session_mgmt__set_session_effort` instead.")


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
            f"\"<its report>\" --kind effort`. Their models stay as they were started:\n" + "\n".join(told))


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
    waits = [f"- {link(k)} holds {n} start request{'s' if n != 1 else ''} only it can start: ezexe opens it and "
             f"presses the button its turn ended on, or sends it one message." for k, n in holders(s)]

    def of_kind(kind):
        return [f"- {PHI.clean(n.get('claim'))} Source: {PHI.clean(n.get('source'))}. Kept {n.get('time', '')}."
                for n in notes if PHI.clean(n.get("kind")) == kind]
    lines += ["", "## Waiting on", ""] + (waits + of_kind("decision") + of_kind("waiting") or ["Nothing."])
    asked = requests_for(s)
    answers = s.get("requestAnswers") if isinstance(s.get("requestAnswers"), dict) else {}
    lines += ["", "## Requests to this puppeteer", ""]
    lines += [f"- {r['id']} \"{r.get('title')}\" from \"{full_title(r.get('requester'))}\": open." for r in asked]
    lines += [f"- {rid} \"{a.get('title', '')}\": declined {a.get('time', '')}: {a.get('why', '')}"
              for rid, a in sorted(answers.items()) if isinstance(a, dict)]
    if not asked and not answers:
        lines.append("None.")
    lines += ["", "## Started on another session's behalf", ""]
    lines += [behalf_row(r) for r, _ in behalf_rows(home, s)] or ["None."]
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
    if rules:                                      # the page the board sends a session to holds the new wording
        PHI.rules_page(home, PHI.memory_rules(home))
    lines += ["", "## Feedback and user memories ezexe changed during the run", ""]
    lines += [f"- {x.get('name')}, {x.get('time', '')}" for x in rules] or ["None."]
    if rules:
        lines.append(f"Each is whole on {os.path.join(home, 'phi', 'rules.md').replace(chr(92), '/')}.")
    other = [f"- {PHI.clean(n.get('claim'))} Source: {PHI.clean(n.get('source'))}. Kept {n.get('time', '')}."
             for n in notes if PHI.clean(n.get("kind")) not in ("decision", "parked", "waiting")]
    lines += ["", "## Notes", ""] + (other or ["None."])
    lines += ["", "## Archived and left", ""]
    lines += [f"- {'archived' if a.get('let') else 'left'} {a.get('time', '')}: \"{a.get('title', '')}\" "
              f"`{a.get('sessionId', '')}`: {a.get('why', '')}"
              for a in s.get("puppeteerArchives") or [] if isinstance(a, dict)] or ["None."]
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
    """Where each controlled session stands, and the archive calls p4-phi let through or refused."""
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
    for a in [a for a in s.get("puppeteerArchives") or [] if isinstance(a, dict)]:
        lines.append(f"- {'archived' if a.get('let') else 'left'} {a.get('time', '')}: \"{a.get('title', '')}\" "
                     f"`{a.get('sessionId', '')}`: {a.get('why', '')}")
    lines.append(f"The board: {board_path(home, s['sessionId'])}")
    return "\n".join(lines)


# --- the archive guard -----------------------------------------------------------------------------------------------------

def control_store(home, s, target):
    """The store of a session a puppeteer may archive on ezexe's pick: one it controls, one in such a
    session's tree, one in its own tree, or the puppeteer that handed over to it; None when it is none of
    those."""
    rows = {e["sessionId"]: e.get("store") or "" for e in controlled(s)}
    if target in rows:
        return rows[target]
    store = store_of(target)
    for above in (PHI.chain_of(store, target) if store else []):
        if above in rows:
            return store
    if s["sessionId"] in PHI.chain_of(home, target):
        return home
    if target == (s.get("handedFrom") or {}).get("sessionId"):
        return store
    return None


NOT_PICKED = ("Not picked by ezexe in this turn: a puppeteer archives only what ezexe picks, by the button "
              "or the multiple-choice question p4-phi hands it")
PICKED = "ezexe picked it in this turn"
BUTTON_YES, BUTTON_NO = "Archive it", "Not now"
OFFER_MAX = 4                    # options one question of an AskUserQuestion holds
QUESTIONS_MAX = 4                # questions one AskUserQuestion holds


def archive(home, s, target, reason, picked=False):
    """A puppeteer's archive of another session. Returns an empty string to let it through, else why it is
    refused. It is let through only when ezexe picked the session in this turn and p4-phi's records hold it
    complete. Kept either way on the puppeteer's record, so what was archived and what was left is read
    from one place."""
    target = PHI.safe_id(target)
    store = control_store(home, s, target)
    if store is None:
        why = (f"{target} is not a session this puppeteer controls, nor in the tree of one: "
               f"`{PHI.commands()} controls <sessionId>` records an orchestrator ezexe put under it")
    else:
        _, against = standing(store, target)
        why = ""
        if against:
            why = "p4-phi's records do not hold it complete: " + "; ".join(against)
        elif not picked:
            why = NOT_PICKED.format(cmd=PHI.commands()) + ". p4-phi's records hold it complete, so it can be offered"
        if against and not picked:
            why += ". " + NOT_PICKED.format(cmd=PHI.commands())[0].upper() + NOT_PICKED.format(cmd=PHI.commands())[1:]
        reason = PHI.clean(reason) if len(PHI.clean(reason)) >= REASON_MIN else PICKED
    kept = [a for a in s.get("puppeteerArchives") or [] if isinstance(a, dict)]
    kept.append({"sessionId": target, "title": full_title(target), "time": PHI.now(), "let": not why,
                 "why": PHI.cut(PHI.clean(why or reason), 300)})
    s["puppeteerArchives"] = kept[-KEPT:]
    PHI.save_session(home, s)
    return why


def complete(home, s):
    """Returns two lists: the sessions a puppeteer can offer ezexe to archive, each as its sessionId, its
    full title and the finished sessions of its tree, and the ones it cannot, each as its full title and why it is
    not offered. A controlled session, or the puppeteer that handed over to this one, is offered when the
    app has not archived it and p4-phi's records hold nothing against it."""
    ready, left = [], []
    rows = [(e["sessionId"], e.get("store") or "") for e in controlled(s)]
    old = PHI.safe_id((s.get("handedFrom") or {}).get("sessionId") or "") if isinstance(s.get("handedFrom"), dict) else ""
    if old and old not in [k for k, _ in rows]:
        rows.append((old, control_store(home, s, old) or ""))
    for sid, store in rows:
        state, against = standing(store, sid)
        if state == "archived":
            continue
        if state == "shown done" and not against:
            kids = [k for k, _, _ in relay.ready_in_tree(store, sid)] if store else []
            ready.append((sid, full_title(sid), kids))
        else:
            left.append((full_title(sid), "; ".join(against) or "p4-phi's records do not show its task done"))
    return ready, left


def offer(home, s, button=True):
    """The options a puppeteer puts to ezexe: one for each complete controlled session, by its full title
    and with the finished sessions of its tree, each a dict of its label, description and ids. The labels are what
    the archive hook reads ezexe's picks by, so they are kept on the puppeteer's record; the caller saves
    it."""
    ready, _ = complete(home, s)
    if not ready:
        s.pop("archiveOffer", None)
        return []

    def about(sid, kids):
        return f"Archive {sid}" + (f" and the {len(kids)} finished session{'s' if len(kids) != 1 else ''} of its "
                                   f"tree" if kids else "") + "."
    opts = [{"label": title, "description": about(sid, kids), "ids": [sid] + kids} for sid, title, kids in ready]
    seen = {}
    for o in opts:                                 # a label is the key a pick is read by: each one once
        seen[o["label"]] = seen.get(o["label"], 0) + 1
        if seen[o["label"]] > 1:
            o["label"] += f" ({seen[o['label']]})"
    kept = [{"label": o["label"], "ids": o["ids"]} for o in opts]
    if len(ready) == 1 and button:                 # one session: a button, whose press is ezexe's next message
        kept.append({"label": BUTTON_YES, "ids": opts[0]["ids"], "button": True})
    s["archiveOffer"] = kept
    return opts


def offer_text(home, s, button=True):
    """The line that puts a puppeteer's complete sessions to ezexe, and an empty string when none is
    complete. It names the button or the multiple-choice questions and never the archive call, which follows ezexe's
    pick. One session is a button on the turn's wrap-up when `button`; where the wrap-up already holds a question,
    it is a multiple-choice question of one option. Past OFFER_MAX sessions, the options are split as evenly as they
    go into questions of at most OFFER_MAX options, QUESTIONS_MAX questions to one AskUserQuestion."""
    opts = offer(home, s, button)
    ready, left = complete(home, s)
    if not opts:
        return ""
    lead = f"First keep each outcome that is not on the board yet with `{PHI.commands()} note`."
    out = ("" if not left else " Not offered, and named to ezexe as left with the reason: "
           + "; ".join(f"\"{t}\" because {why}" for t, why in left[:6]) + ".")
    if len(ready) == 1 and button:
        sid, title, kids = ready[0]
        return (f"phi (p4-phi): \"{title}\" `{sid}`, a session this puppeteer controls, is complete"
                + (f", with {len(kids)} finished session{'s' if len(kids) != 1 else ''} in its tree" if kids else "")
                + f". Archiving it is ezexe's own pick, never this session's judgement. {lead} Then end the turn "
                f"with `mcp__ccd_turn__wrap_up` whose question is \"Archive \"{title}\"?\", cut to fit, and whose "
                f"buttons are the replies \"{BUTTON_YES}\" and \"{BUTTON_NO}\". Archive nothing in this turn. "
                f"When ezexe presses \"{BUTTON_YES}\", which comes as ezexe's next message, archive exactly "
                + ("that session and those of its tree" if kids else "that session")
                + f" in that turn, and p4-phi lets it through; on anything else leave it and say so.{out}")
    asks = -(-len(opts) // OFFER_MAX)              # questions, each of two to OFFER_MAX options when there are several
    lines = "\n".join((f"Question {k + 1}:\n" if asks > 1 else "") + "\n".join(
        f"- label \"{o['label']}\", description \"{o['description']}\""
        for o in opts[k * len(opts) // asks:(k + 1) * len(opts) // asks]) for k in range(asks))
    into = ("one `AskUserQuestion`" if asks <= QUESTIONS_MAX else
            f"{-(-asks // QUESTIONS_MAX)} `AskUserQuestion` calls of at most {QUESTIONS_MAX} questions")
    how = ("one multiple-choice question: one `AskUserQuestion` with `multiSelect` true" if asks == 1 else
           f"{asks} multiple-choice questions in {into}, each question with a text of its own and `multiSelect` true")
    n = len(ready)
    return (f"phi (p4-phi): {n} session{'s' if n != 1 else ''} this puppeteer controls "
            f"{'are' if n != 1 else 'is'} complete. Archiving {'them' if n != 1 else 'it'} is ezexe's "
            f"own pick, never this session's judgement. {lead} Then, before `mcp__ccd_turn__wrap_up`, put them to "
            f"ezexe as {how}, each option a session by its full title, exactly these options"
            + (", with a last option \"None of them\"" if len(opts) == 1 else "")
            + (" under these questions" if asks > 1 else "") + f":\n{lines}\n"
            f"Archive none of them before ezexe has answered. Then archive exactly the sessions under the options "
            f"ezexe picked, and no other: p4-phi lets through only those. Name "
            f"each one archived and each one left.{out}")


def offered_ids(home, s):
    """The sessions a puppeteer's archive offer can hold: each complete controlled session, and every finished
    session of a controlled tree, as the multiSelect question it puts to ezexe names them."""
    ready, _ = complete(home, s)
    out = {sid for sid, _, _ in ready} | {k for _, _, kids in ready for k in kids}
    for e in controlled(s):
        store = e.get("store") or ""
        if store:
            out |= {k for k, _, _ in relay.ready_in_tree(store, e["sessionId"])}
    return out


def names_of(sid):
    """The full titles a session goes by in ezexe's answer: the app's title, and p4-phi's where it differs."""
    store = store_of(sid)
    k = PHI.load_session(store, sid) if store else {}
    out = [full_title(sid, k), PHI.title_of(k) if k else ""]
    return [x for k_, x in enumerate(out) if x and x not in out[:k_]]


def picked(home, s, turn, named=None):
    """The session ids ezexe picked in this turn: the ids under each offered option whose label an answered
    AskUserQuestion of the turn carries, each session of `named` an answer names by its full title or its id, and
    the ids under the offered button when the turn's own message is that button's label."""
    turn = turn or {}
    out = list(relay.picked(home, s["sessionId"], turn.get("calls"), named))
    said = PHI.clean(turn.get("prompt")).strip(" .!\"'").lower()
    for o in s.get("archiveOffer") or []:
        if isinstance(o, dict) and o.get("button") and said == str(o.get("label") or "").lower():
            out += [i for i in o.get("ids") or [] if i not in out]
    return out


def waited_on(s):
    """The full titles of the controlled sessions a puppeteer may still be waiting on: each one the app has
    not archived that is working, has something open, or is not shown done."""
    out = []
    for e in controlled(s):
        state, _ = standing(e.get("store") or "", e["sessionId"])
        if state in ("working", "open", "not shown done"):
            out.append(full_title(e["sessionId"]))
    return out


# --- a boundary, and the notice that is a button -------------------------------------------------------------------------

def handed_chars(home, s):
    """The characters p4-phi's hooks handed this session since its last compaction, from its own log."""
    since = str(s.get("compactedAt") or "")
    return sum(int(r.get("said") or 0) for r in PHI.read_rows(os.path.join(PHI.session_dir(home, s["sessionId"]),
                                                                           "log.jsonl"))
               if str(r.get("time") or "") >= since)


def boundary(home, s, store=""):
    """The notice a puppeteer is handed once at each boundary, and an empty string otherwise: a boundary is
    a controlled tree that has closed, or every controlled session idle with no request waiting. Never while a
    controlled session waits on the puppeteer's answer. The caller saves what was told."""
    rows = controlled(s)
    if not rows or requests_for(s):
        return ""
    states, closed = [], []
    for e in rows:
        state, _ = standing(e.get("store") or "", e["sessionId"])
        when, _ = last_report(e.get("store") or "", e["sessionId"])
        states.append((e["sessionId"], state, when))
        if state == "archived":
            closed.append(e["sessionId"])
    told = s.get("boundary") if isinstance(s.get("boundary"), dict) else {}
    newly = [k for k in closed if k not in (told.get("closed") or [])]
    idle = all(st != "working" for _, st, _ in states) and not any(
        waiting_requests(e.get("store") or "", e["sessionId"]) for e in rows)
    ready = [sid for sid, _, _ in complete(home, s)[0]]
    fresh = [k for k in ready if k not in (told.get("ready") or [])]
    if not newly and not idle and not fresh:
        return ""
    chars, top = handed_chars(home, s), ceiling(store)
    key = hashlib.sha1(json.dumps([sorted(states), chars // top]).encode("utf-8")).hexdigest()[:12]
    if told.get("key") == key:
        return ""
    s["boundary"] = {"key": key, "closed": closed, "ready": ready, "time": PHI.now()}
    pick = offer_text(home, s, button=not (newly or idle)) if ready else ""    # archived by ezexe's pick
    if pick and not (newly or idle):
        return pick                                # a tree is complete while another works: no boundary yet
    why = (f"the tree of \"{full_title(newly[0])}\" has closed" if newly else
           "every controlled session is idle and no request is waiting")
    path = board_path(home, s["sessionId"])
    past = (f" p4-phi has handed this session {chars} characters since its last compaction, past the ceiling of {top}."
            if chars >= top else "")
    second = ("the app's `new_session` action, which starts the successor puppeteer from the board; its brief "
              f"is the board's path and `{PHI.commands()} controls --from {s['sessionId']}`, and this session then runs "
              f"`{PHI.commands()} controls --hand <its sessionId>`"
              if int(s.get("compactions") or 0) >= COMPACTIONS else "\"Later\"")
    return ((pick + "\n\n" if pick else "") +
            f"phi (p4-phi): a boundary: {why}.{past} When this turn's messages are sent, keep what is not yet on the "
            f"board, {path}, with `{PHI.commands()} note`. Then read the context usage with "
            f"`mcp__ccd_session_mgmt__get_usage` on `\"self\"` and end the turn with `mcp__ccd_turn__wrap_up` whose "
            f"question is one short sentence with that usage, such as \"Context is at 71%, auto-compact starts at "
            f"85%. Compact now?\", and whose buttons are \"Compact now\" and {second}. On \"Compact now\" answer "
            f"with one line only, for ezexe to type, since a session cannot compact itself and no button sends a "
            f"command: `/compact keep the path of the board, {path}, and read it first`. On "
            f"\"Later\" say nothing more.")


def compacted(home, s):
    """A puppeteer after a compaction: the count starts again, and its board's path comes first."""
    s["compactedAt"] = PHI.now()
    s["compactions"] = int(s.get("compactions") or 0) + 1
    s.pop("boundary", None)
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
            f"this session's outcome with `note` and offers it to ezexe to archive, as any complete session it "
            f"controls: it archives this session only on ezexe's pick, by the button or the multiple-choice question "
            f"p4-phi hands it")


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


# --- start requests stay with the session that filed them ----------------------------------------------------------------

def stores(home, s):
    """This puppeteer's own store and those of the sessions it controls, each once."""
    out = {}
    for where in [home] + [e.get("store") or "" for e in controlled(s)]:
        if where:
            out.setdefault(os.path.normcase(os.path.abspath(where)), where)
    return list(out.values())


def holders(s):
    """Each live session of the trees a puppeteer controls that holds start requests a turn ezexe begins
    in it would start, as its sessionId and how many, tree by tree."""
    out, held = [], {}
    for e in controlled(s):
        top, store = e["sessionId"], e.get("store") or ""
        if store not in held:
            held[store] = [r.get("requester") for r in starts.pending(store)] if store else []
        for sid in dict.fromkeys(held[store]):
            if sid and (sid == top or top in PHI.chain_of(store, sid)) \
                    and not out_of_tree(PHI.load_session(store, sid)):
                out.append((sid, held[store].count(sid)))
    return out


def holders_text(s, req=""):
    """The line a puppeteer is handed while sessions of the trees it controls hold start requests: each as
    a link with how many it holds, and no start call. Handed at each turn ezexe begins, and at another turn when what
    is held has changed; the caller saves what was told."""
    rows = holders(s)
    if not rows:
        s.pop("holdersTold", None)
        return ""
    key = [[k, n] for k, n in rows]
    if not req and s.get("holdersTold") == key:
        return ""
    s["holdersTold"] = key
    return ("phi (p4-phi): sessions of the trees this puppeteer controls hold start requests that only they "
            "can start, each at a turn ezexe begins in it by the button its turn ended on, so the app nests each child "
            "under the session that asked for it. Start none of them here: a start request belongs under the session "
            "that filed it, and a start made here nests the child under this puppeteer, where no tool moves "
            "it from. End this turn with these lines as they are, each a link ezexe opens:\n"
            + "\n".join(f"- {link(k)}: {n} start request{'s' if n != 1 else ''}" for k, n in rows))


def behalf(home, s, prompt, store=""):
    """The start request another session filed for a child of its own and the store it lies in, when a start call of
    this puppeteer carries its marker; None for any other call or session."""
    m = starts.MARK_RE.search(str(prompt or ""))
    if not m or not s.get("sessionId") or m.group(2) == s["sessionId"] or not is_puppeteer(s, store):
        return None
    for where in stores(home, s):
        r = starts.state(where).get(m.group(1))
        if r and r.get("requester") == m.group(2) and not r.get("to"):
            return r, where
    return None


def behalf_line(r):
    """What a puppeteer is told as its start of another session's start request goes through."""
    return (f"phi (p4-phi): this start carries start request {r['id']} of {link(r['requester'])}, which belongs under "
            f"that session, while the app nests the new session under this puppeteer. p4-phi records it as "
            f"started on that session's behalf, holds the new session under that session and names it on the board "
            f"as an exception. Once the start returns, call `mcp__ccd_session_mgmt__detach_session` with the new "
            f"session's id, so the app shows it at top level and not under this puppeteer. Start no other "
            f"session's request here: name the session that holds it to ezexe as a link to open.")


def behalf_rows(home, s):
    """The start requests of other sessions that this puppeteer started, each with the store it lies in."""
    return [(r, where) for where in stores(home, s) for r in starts.state(where).values()
            if (r.get("claimed") or {}).get("by") == s["sessionId"] and r.get("requester") != s["sessionId"]
            and not r.get("to")]


def behalf_row(r):
    """A start made on another session's behalf as the board names it: what the app shows of the new session."""
    kid = str(r.get("started") or "")
    head = (f"- start request {r['id']} \"{r.get('title')}\" of {link(r['requester'])}, which this puppeteer "
            f"started")
    if kid == "withdrawn" or not kid:
        return head + (", withdrawn since." if kid else ": its session has not reached p4-phi's records yet.")
    return (head + f" as {link(kid)}: p4-phi holds it under that session, and the app "
            + ("shows it at top level." if PHI.app_record(kid).get("lineageDetached") else
               "nests it under this puppeteer until it is detached to top level with "
               "`mcp__ccd_session_mgmt__detach_session`."))


def behalf_text(home, s):
    """The line naming each session this puppeteer started on another session's behalf that the app still
    nests under it, once each, with the call that detaches it to top level; the caller saves what was told."""
    told = [x for x in s.get("behalfTold") or [] if isinstance(x, str)]
    named = []
    for r, _ in behalf_rows(home, s):
        kid = str(r.get("started") or "")
        rec = PHI.app_record(kid) if kid.startswith("local_") else {}
        if not rec or kid in told or rec.get("lineageDetached") or rec.get("isArchived"):
            continue
        told.append(kid)
        named.append(f"- {link(kid)}, started for start request {r['id']} of {link(r['requester'])}: call "
                     f"`mcp__ccd_session_mgmt__detach_session` with `{kid}`")
    if not named:
        return ""
    s["behalfTold"] = told[-50:]
    return ("phi (p4-phi): this puppeteer started these sessions on another session's behalf, so the app "
            "nests each under it while p4-phi holds each under the session that filed its start request. Detach to "
            "top level each one now, so the app never shows it under this puppeteer; the board names each "
            "as an exception:\n" + "\n".join(named))


# --- requests through the puppeteer ------------------------------------------------------------------------------

def request_call(r):
    """The exact start_session input for a request addressed to a puppeteer: a new orchestrator in
    the environment of the session that filed the request."""
    project = os.path.dirname(os.path.dirname(os.path.abspath(r["store"]))).replace("\\", "/")
    bg = str(r.get("background") or "")
    if len(bg) < starts.BACKGROUND_MIN:
        bg = starts.background_of(r["store"], r["requester"], bg)
    brief = r["brief"]
    if not PHI.NEW_TOP.search(brief):
        brief += "\n\n" + PHI.NEW_TOP_BRIEF + " " + PHI.new_top_first_act()
    return plans.with_level({"initiation": "user_asked", "title": r["title"], "context": "fresh",
                             "use_worktree": False, "cwd": project, "background": bg,
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
            "began, so for each either start it with exactly the call given and then file it with "
            "`mcp__ccd_sidebar__move_sessions` where named, never in the section this session is filed in, or decline "
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


# --- a go to a waiting writer --------------------------------------------------------------------------------------------

def go_text(home, s, target, message=""):
    """A puppeteer's message to a session it controls. Returns one line when another controlled session,
    or a session in its tree, still holds a file of that writer's write set: the holder by full title, and what
    frees the files. Returns an empty string when nothing is held or this go and its holders were warned of
    already. The write set is the one the message declares on a `Files:` line, else the one the target declared."""
    target = PHI.safe_id(target) if target else ""
    rows = controlled(s)
    mine = next((e for e in rows if e["sessionId"] == target), None)
    if not mine:
        return ""
    store = mine.get("store") or ""
    t = PHI.load_session(store, target) if store else {}
    files = starts.files_of(message, t.get("cwd") or "") or [x for x in t.get("fileSet") or [] if isinstance(x, str)]
    if not files:
        return ""
    held = []
    for e in rows:
        st = e.get("store") or ""
        if e["sessionId"] == target or not st:
            continue
        for sid, _, theirs in starts.writers(st):
            above = PHI.chain_of(st, sid)
            if sid == target or target in above or (sid != e["sessionId"] and e["sessionId"] not in above):
                continue
            hit = starts.files_overlap(files, theirs)
            if hit:
                held.append((sid, full_title(sid), hit))
    if not held:
        return ""
    key = hashlib.sha1(json.dumps([target, sorted((sid, hit) for sid, _, hit in held)]).encode("utf-8")).hexdigest()[:12]
    told = [k for k in s.get("goWarned") or [] if isinstance(k, str)]
    if key in told:
        return ""
    s["goWarned"] = (told + [key])[-40:]
    names = "; ".join(f"\"{title}\" `{sid}` holds {', '.join(hit[:4])}" for sid, title, hit in held[:4])
    return (f"phi (p4-phi): this go to \"{full_title(target)}\" is early: {names}. Hold the go until that session "
            f"reports done, or have it release what "
            f"it has landed with `{PHI.commands()} files --release` or `{PHI.commands()} files <the paths it still "
            f"writes>` first. Said once for this go and these holders.")


# --- work sent down to a controlled session --------------------------------------------------------------------------------

def route_down(s, words_):
    """The line that sends ezexe's message to a puppeteer on to the controlled session whose topic covers
    it, and an empty string when no controlled session's topic covers it."""
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
    if not best:
        return ""
    sid = best["sessionId"]
    return (f"phi (p4-phi): this message reads as work on the topic \"{full_title(sid)}\" `{sid}` orchestrates. If so, "
            f"do not do it here and start no child for it: send that session one message with SendMessage, holding "
            f"{PHI.RESTATE}, and telling it to brief and start a worker of its own for it. Keep it on the board with `{PHI.commands()} note \"<what was sent "
            f"and to whom>\" --source \"<the message>\" --kind waiting` until its report comes.")
