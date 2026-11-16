"""controls.py: a puppeteer and the sessions it controls (#58).

ezexe files a top session in the sidebar section "puppeteers" and it controls the topmost orchestrating sessions of
one or more environments, an environment being a project with its own store. The mark is a pair: the puppeteer,
and the session or sessions it controls. A controlled session stays the top of its own tree, in its own section.
Since #38 puppeteer.py is every orchestrator's watcher; the puppeteer here is the narrower one, the session in the
section.

  the mark   A hook cannot call the app's tools, but the app keeps the sidebar on disk: claude_desktop_config.json,
             beside the claude-code-sessions folder, holds preferences.epitaxyPrefs["dframe-group-scopes"], each
             scope with `groups` ({id, name}) and `assignments` ({"code:<sessionId>": group id}). Read 2026-11-16.
             phi reads the filing there each time it matters and keeps no mark of its own. A file that is missing
             or shaped otherwise makes nobody a puppeteer. Nothing stops a session from filing itself, since the
             app asks nobody: the rule rests on ezexe's filing, and phi says once, in the session and on its
             record, that it saw the session there, and tells every session it lists who claims it.
  the pair   `controls` on the puppeteer's session.json lists the sessions it controls, each with the store its
             tree lives in. The record is where every top session's is: the store of the folder it was opened in.
             A controlled session's own hook finds the pair and keeps `puppeteer` on its own record. Each side
             reads the other's store and neither writes into it.
  the board  <the puppeteer's session folder>/board.md, rewritten by its hooks: each controlled session in a line
             with the path of its page, the requests addressed to the puppeteer, the rules that changed during
             the run, its notes by kind, and the archive calls let through or refused. After a compaction its
             path is the first thing the puppeteer is handed.
  a boundary a controlled tree has closed, or every controlled session is idle with no request waiting. The
             puppeteer is told once to end its turn on a question with two buttons, as a done top session ends
             on the archive button. phi speaks only when a hook fires, so a boundary reached while the puppeteer
             is idle is told beside its next message.
  archiving  a puppeteer never archives on its own judgement (#63). A complete controlled session is offered to
             ezexe, one as a button and several as one quick select by full title, and the archive hook lets
             through only what ezexe picked in that turn. The completeness checks decide what is offered.
  requests   a controlled top session that would start a new top session writes `request ... --to-puppeteer`
             into its own store; the puppeteer's hooks read it there, and what became of it is kept on the
             puppeteer's record, where the requester's hook reads it.
"""

import hashlib
import json
import os
import time

import issues
import p4conf
import plans
import relay
import starts

PHI = None                       # phi's own module, handed over when phi imports this one

SECTION = "puppeteers"           # p4.json phi.puppeteer_section; "" turns the rule off
CHARS = 200000                   # p4.json phi.puppeteer_chars: what phi may hand a puppeteer between compactions
COMPACTIONS = 3                  # after this many, the notice offers a successor in place of "Later"
KEPT = 100                       # archive calls kept on a puppeteer's record
REASON_MIN = 12                  # characters of a reason that says something
RECENT = 120                     # the app's newest records looked through for sessions a puppeteer started
SHARE = 2                        # content words a message shares with a controlled session's topic to be routed
_SECTIONS = {}                   # the app's file, read once a process: {"all": {sessionId: section name}}


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
    """{sessionId: the name of the sidebar section the app's own file assigns it to}."""
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
    """True for a puppeteer: a top session the app's file shows filed in the section."""
    sid = str(s.get("sessionId") or "") if isinstance(s, dict) else ""
    want = section_name(store).lower()
    return bool(want and sid and not PHI.spawned_from(s) and section_of(sid).strip().lower() == want)


def full_title(sid, s=None):
    """A session's whole title as the app lists it, else what phi holds."""
    return PHI.clean(PHI.app_record(sid).get("title")) or PHI.title_of(s or {"sessionId": sid})


def out_of_tree(s):
    """A session phi holds as over, read without writing to its store."""
    return bool(not isinstance(s, dict) or s.get("stale") or s.get("doneRetired") or s.get("archived")
                or relay.archived_in_app(s))


def store_of(sid):
    """The store a session's tree lives in, by the app's record; '' when it cannot be told."""
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
    """Where a controlled session stands, from the app's record and its own store, written nowhere ->
    (state, [what phi's records hold against archiving it]). The state is one of archived, unread, working, open,
    shown done, not shown done."""
    rec = PHI.app_record(sid)
    if not rec:
        return "unread", ["the app holds no record of it on this machine"]
    if rec.get("isArchived"):
        return "archived", []
    s = PHI.load_session(store, sid) if store else {}
    if not s.get("sessionId"):
        return "unread", ["phi finds no record of it in a store, so its turn and steps are unread"]
    against = []
    working = _watcher().working(store, sid)
    if working:
        against.append("its last message has no turn's end recorded after it, so it is mid-turn")
    steps = plans.open_steps(store, sid)
    if steps:
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
                       f"\"{asked[0].get('title')}\": ezexe has to speak in that session, or press its card")
    try:
        for path, sha, _, closes in relay.closing_commits(store, sid, s):
            if not issues._pushed(path, sha):
                against.append(f"commit {sha}, which closes #{', #'.join(closes)}, is on no remote branch")
    except Exception:  # noqa: BLE001
        pass
    turns = PHI.load_turns(store, sid)
    every = plans.load(store, sid).get("steps") or []
    shown = bool(turns and turns[-1].get("done")) or bool(every) and not steps
    return ("working" if working else "open" if against else "shown done" if shown else "not shown done"), against


def last_report(store, sid):
    """(when, the first line of a session's last report), ('', '') when it has no turn."""
    turns = PHI.load_turns(store, sid) if store else []
    if not turns:
        return "", ""
    text = str(turns[-1].get("report") or "").strip().split("\n", 1)[0]
    return str(turns[-1].get("time") or ""), PHI.cut(PHI.clean(text), 200)


# --- the pair -----------------------------------------------------------------------------------------------------------

RULE = (
    "This session is a puppeteer: ezexe filed it in the sidebar section \"{section}\", so it controls the top "
    "sessions of other trees, which stay tops of their own trees in their own sections, siblings and never its "
    "children. Record them with `{cmd} controls <sessionId> ...`; `{cmd} controls` then prints where each stands, "
    "to tell ezexe in one place, each by its full title. Its board, {board}, is rewritten by phi; what phi cannot "
    "see goes on it through `{cmd} note`, with `--kind decision` for what waits on ezexe, `--kind waiting` for what "
    "waits on a session and `--kind parked` for a parked issue. It relays ezexe's rule changes to all of them. It writes no plugin or project files. Work ezexe "
    "gives it on a topic a controlled session orchestrates goes to that session in one message, and that session "
    "starts its own child; a topic none covers gets a new top session that this puppeteer starts and then files in "
    "its environment's section with `mcp__ccd_sidebar__move_sessions`, never in \"{section}\". Waiting on their "
    "reports, and the few read-only checks of their results against git and GitHub, are its own work and never a "
    "child's; its turn may end while it waits, with a line naming whom it waits on. It never archives a session "
    "on its own judgement: a session is archived by ezexe's own pick. When a session it controls is complete, it "
    "first keeps the outcome with `{cmd} note`, then puts the choice to ezexe: one session as a button on "
    "`mcp__ccd_turn__wrap_up`, several as one `AskUserQuestion` with `multiSelect` listing each by its full "
    "title, with the options phi hands it. It archives exactly what ezexe picked in that turn, and phi refuses "
    "every other archive call. phi offers no session that is mid-turn, has open steps, a running background task "
    "or a start request waiting, or has an issue-closing commit on no remote branch, and says which reason keeps "
    "each one off the list. It names each session it archived and each it left, with the reason. Deleting data, "
    "force pushes and publishing still need ezexe's yes in the session that acts: being a "
    "puppeteer widens nothing there.")
PAIR = (
    "This session has a puppeteer: \"{title}\" ({pid}), a session ezexe filed in the sidebar section \"{section}\", "
    "lists this one among the sessions it controls. This session stays the top of its own tree, in its own "
    "section, with its own steerer and lander, and still pushes its own work. Its puppeteer reads its state, "
    "relays ezexe's rule changes, may decline a request this session sends it, and, once this session and the "
    "sessions of its tree are complete, offers them to ezexe to archive and archives only the ones ezexe picks. A new top session is asked of the puppeteer and never "
    "started here: `{cmd} request \"<title>\" --brief \"<the whole brief>\" --to-puppeteer`. Anything irreversible "
    "or outward still needs ezexe's yes in this session, whoever relays the request.")
PAIR_OVER = ("This session no longer has a puppeteer: \"{title}\" ({pid}) dropped it from the sessions it controls, "
             "or left the sidebar section. It is a top session as before, and starts its own new top sessions again.")
ASK = ("phi (p4-phi): this session has a puppeteer, so where a line here says to start a new top session, start "
       "none: write `{cmd} request \"<title>\" --brief \"<the whole brief>\" --to-puppeteer`, the brief declaring "
       "its file set on a line `Files: <paths>`. Its puppeteer \"{title}\" starts it, files it in this environment's "
       "section and takes it under control, or declines it with one line to ezexe.")


def board_path(home, sid):
    return os.path.join(PHI.session_dir(home, sid), "board.md").replace("\\", "/")


def rule_text(home, s):
    return RULE.format(section=section_of(s["sessionId"]), cmd=PHI.commands(), board=board_path(home, s["sessionId"]))


def control(home, s, add=(), drop=()):
    """Record or drop the sessions a puppeteer controls -> the lines to print."""
    rows, out = controlled(s), []
    for sid in [PHI.safe_id(x) for x in drop]:
        if any(e["sessionId"] == sid for e in rows):
            rows = [e for e in rows if e["sessionId"] != sid]
            out.append(f"no longer controlled: {sid}")
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
            raise ValueError(f"{sid} was started by another session: a puppeteer controls top sessions, and a "
                             f"child is reached through its top")
        if not any(e["sessionId"] == sid for e in rows):
            rows.append({"sessionId": sid, "store": store, "time": PHI.now()})
            out.append(f"controlled: \"{full_title(sid)}\" ({sid})" + (f", store {store}" if store else ""))
    _set(s, rows)
    PHI.save_session(home, s)
    return out


def puppeteer_of(s, store=""):
    """(the puppeteer's sessionId, its store) of a top session some puppeteer lists under `controls`; ('', '')."""
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
    """What a session is told, once, when it comes to have a puppeteer, and once when it no longer has one. Its
    own record keeps the puppeteer's id; the caller saves it."""
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
    """In place of phi's own way to a new top session, for a session that has a puppeteer."""
    held = s.get("puppeteer") if isinstance(s.get("puppeteer"), dict) else {}
    if not held.get("sessionId"):
        return ""
    return (f"This session has a puppeteer, so it starts no new top session itself: write `{PHI.commands()} request "
            f"\"<title>\" --brief \"<the whole brief>\" --to-puppeteer`, the brief holding the topic, ezexe's words "
            f"quoted and its file set on a line `Files: <paths>`. Its puppeteer \"{full_title(held['sessionId'])}\" "
            f"starts it as a top session of this environment, files it in this environment's section and takes it "
            f"under control, or declines it with one line to ezexe.")


def ask_text(s):
    """The line that turns a controlled session's own start of a new top session into a request."""
    held = s.get("puppeteer") if isinstance(s.get("puppeteer"), dict) else {}
    return ASK.format(cmd=PHI.commands(), title=full_title(held["sessionId"])) if held.get("sessionId") else ""


# --- sessions that come under control without a command ----------------------------------------------------------------

def started_by(sid):
    """The live sessions whose app record names `sid` as their starter, among the app's newest records."""
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
    """Where a new top session of an environment is filed: the section its controlled siblings are in."""
    for e in controlled(s):
        if e.get("store") == store and section_of(e["sessionId"]):
            return f"the section \"{section_of(e['sessionId'])}\""
    return "the ungrouped list under its project"


def take_started(home, s):
    """A top session this puppeteer started is recorded as controlled, and the section to file it in is named."""
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
        lines.append(f"\"{full_title(sid, k)}\" ({sid}) is a top session this puppeteer started, so it is now "
                     f"controlled. File it in {where} with `mcp__ccd_sidebar__move_sessions`, never in "
                     f"\"{section_of(s['sessionId'])}\".")
    if lines:
        _set(s, rows)
    return lines


def announce(home, s):
    """A top session ezexe started directly in a store this puppeteer controls a session in, named once."""
    told, lines = [x for x in s.get("announced") or [] if isinstance(x, str)], []
    have = {e["sessionId"] for e in controlled(s)} | {s["sessionId"]}
    first = {}
    for e in controlled(s):
        if e.get("store"):
            first[e["store"]] = min(first.get(e["store"], "9"), str(e.get("time") or ""))
    for store, since in first.items():
        for sid, k in sorted(relay._sessions(store).items()):
            if sid in have or sid in told or PHI.spawned_from(k) or out_of_tree(k) \
                    or not sid.startswith("local_") or not PHI.app_record(sid) \
                    or str(k.get("createdAt") or "") < since or is_puppeteer(k, store):
                continue
            told.append(sid)
            lines.append(f"\"{full_title(sid, k)}\" ({sid}) is a new top session in {store} that this puppeteer does "
                         f"not control: `{PHI.commands()} controls {sid}` takes it under control.")
    if lines:
        s["announced"] = told[-200:]
    return lines


# --- reports by reference -----------------------------------------------------------------------------------------------

def reports(s):
    """One line a controlled session whose last turn ended since the puppeteer last looked, with its page's
    path, never the report's text. The caller saves what was seen."""
    seen = dict(s.get("controlSeen") or {}) if isinstance(s.get("controlSeen"), dict) else {}
    lines = []
    for e in controlled(s):
        sid, store = e["sessionId"], e.get("store") or ""
        when, first = last_report(store, sid)
        if not when or seen.get(sid) == when:
            continue
        seen[sid] = when
        state, _ = standing(store, sid)
        lines.append(f"- \"{full_title(sid)}\" ({sid}) ended a turn at {when}, {state}: {first} Its page: "
                     f"{page_of(store, sid)}")
    if lines:
        s["controlSeen"] = seen
    return lines


# --- the board ------------------------------------------------------------------------------------------------------------

def requests_for(s):
    """The open requests controlled sessions addressed to this puppeteer, read where they lie, not yet answered."""
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


def board(home, s):
    """board.md rewritten when what it holds changed -> its path."""
    sid = s["sessionId"]
    notes = PHI.load_notes(home, sid)
    lines = [f"# Puppeteer board: {full_title(sid, s)} ({sid})", "",
             "Rewritten by p4-phi's hooks, never by hand.",
             f"What is not here is kept with `phi.py note`, and after a compaction this page is read first.", "",
             "## Controlled sessions", ""]
    waits = []
    for e in controlled(s):
        k, store = e["sessionId"], e.get("store") or ""
        state, against = standing(store, k)
        when, first = last_report(store, k)
        lines.append(f"- \"{full_title(k)}\" `{k}`, store {store or 'unknown'}: {state}"
                     + (": " + "; ".join(against) if against else "") + "."
                     + (f" Last report {when}: {first}" if when else "")
                     + (f" Page: {page_of(store, k)}" if store else ""))
        asked = waiting_requests(store, k)
        if asked:
            waits.append(f"- ezexe has to speak in \"{full_title(k)}\" `{k}`, or press its card: it has "
                         f"{len(asked)} child session{'s' if len(asked) != 1 else ''} waiting to be started.")
    if not controlled(s):
        lines.append("None yet.")

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
    lines += ["", "## Parked", ""] + (of_kind("parked") or ["Nothing."])
    rules = [x for x in s.get("rulesChanged") or [] if isinstance(x, dict)]
    lines += ["", "## Rules ezexe changed during the run", ""]
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
    """The rules a `live_rules` text names as changed or added, kept for the board; the caller saves."""
    import re
    names = re.findall(r"(?m)^- memory ([\w.-]+):", str(text or "").split("Removed, no longer rules:")[0])
    if names:
        kept = [x for x in s.get("rulesChanged") or [] if isinstance(x, dict)]
        kept += [{"name": n, "time": PHI.now()} for n in dict.fromkeys(names)]
        s["rulesChanged"] = kept[-60:]


def controls_text(home, s):
    """Where each controlled session stands, and the archive calls phi let through or refused."""
    lines = []
    for e in controlled(s):
        state, against = standing(e.get("store") or "", e["sessionId"])
        lines.append(f"- \"{full_title(e['sessionId'])}\" ({e['sessionId']}), store {e.get('store') or 'unknown'}: "
                     f"{state}" + (": " + "; ".join(against) if against else ""))
    if not lines:
        lines.append("no session is controlled yet: `controls <sessionId> ...` records the top sessions ezexe put "
                     "under this one")
    if s.get("puppeteerSeen"):
        lines.append(f"phi first saw this session in the section at {s['puppeteerSeen']}.")
    for a in [a for a in s.get("puppeteerArchives") or [] if isinstance(a, dict)]:
        lines.append(f"- {'archived' if a.get('let') else 'left'} {a.get('time', '')}: \"{a.get('title', '')}\" "
                     f"({a.get('sessionId', '')}): {a.get('why', '')}")
    lines.append(f"The board: {board_path(home, s['sessionId'])}")
    return "\n".join(lines)


# --- the archive guard -----------------------------------------------------------------------------------------------------

def control_store(home, s, target):
    """The store of a session a puppeteer may archive: one it controls, one in such a session's tree, one in its
    own tree, or the puppeteer that handed over to it; None when it is none of those."""
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


NOT_PICKED = ("ezexe did not pick it in this turn, and a puppeteer archives only what ezexe picks (ezexe/p4#63): "
              "keep its outcome with `{cmd} note`, then put the choice to ezexe, one session as a button on "
              "`mcp__ccd_turn__wrap_up`, several as one `AskUserQuestion` with `multiSelect` listing each by its "
              "full title, and archive exactly what ezexe picks")
PICKED = "ezexe picked it in this turn's quick select"
BUTTON_YES, BUTTON_NO = "Archive it", "Not now"
OFFER_MAX = 4                    # options one AskUserQuestion holds


def archive(home, s, target, reason, picked=False):
    """A puppeteer's archive of another session -> '' to let it through, else why it is refused. It is let through
    only when ezexe picked the session in this turn (#63) and phi's records hold it complete. Kept either way on
    the puppeteer's record, so what was archived and what was left is read from one place."""
    target = PHI.safe_id(target)
    store = control_store(home, s, target)
    if store is None:
        why = (f"{target} is not a session this puppeteer controls, nor in the tree of one: `{PHI.commands()} "
               f"controls <sessionId>` records a top session ezexe put under it")
    else:
        _, against = standing(store, target)
        why = ""
        if against:
            why = "phi's records do not hold it complete: " + "; ".join(against)
        elif not picked:
            why = NOT_PICKED.format(cmd=PHI.commands()) + ". phi's records hold it complete, so it can be offered"
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
    """The sessions a puppeteer can offer ezexe to archive, and the ones it cannot ->
    ([(sessionId, full title, [the finished sessions of its tree])], [(full title, why it is not offered)]). A
    controlled session, or the puppeteer that handed over to this one, is offered when the app has not archived it
    and phi's records hold nothing against it."""
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
            left.append((full_title(sid), "; ".join(against) or "phi's records do not show its task done"))
    return ready, left


def offer(home, s, button=True):
    """The quick select a puppeteer puts to ezexe -> [{"label", "description", "ids"}], one option a complete
    controlled session by its full title, each with the finished sessions of its tree. The labels are what the
    archive hook reads ezexe's picks by, so they are kept on the puppeteer's record; the caller saves it."""
    ready, _ = complete(home, s)
    if not ready:
        s.pop("archiveOffer", None)
        return []

    def about(sid, kids):
        return f"Archive {sid}" + (f" and the {len(kids)} finished session{'s' if len(kids) != 1 else ''} of its "
                                   f"tree" if kids else "") + "."
    opts = [{"label": title, "description": about(sid, kids), "ids": [sid] + kids} for sid, title, kids in ready]
    if len(opts) > OFFER_MAX:
        opts = [{"label": f"All {len(ready)} complete sessions", "description": "Archive every one of them: "
                 + "; ".join(f"\"{t}\"" for _, t, _ in ready) + ".",
                 "ids": [i for o in opts for i in o["ids"]]}] + opts[:OFFER_MAX - 1]
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
    """The line that puts a puppeteer's complete sessions to ezexe, '' when none is complete. It names the button
    or the quick select and never the archive call: that follows ezexe's pick. One session is a button on the
    turn's wrap-up when `button`; where the wrap-up already holds a question, it is a quick select of one."""
    opts = offer(home, s, button)
    ready, left = complete(home, s)
    if not opts:
        return ""
    lead = f"First keep each outcome that is not on the board yet with `{PHI.commands()} note`."
    out = ("" if not left else " Not offered, and named to ezexe as left with the reason: "
           + "; ".join(f"\"{t}\" ({why})" for t, why in left[:6]) + ".")
    if len(ready) == 1 and button:
        sid, title, kids = ready[0]
        return (f"phi (p4-phi): \"{title}\" ({sid}), a session this puppeteer controls, is complete"
                + (f", with {len(kids)} finished session{'s' if len(kids) != 1 else ''} in its tree" if kids else "")
                + f". Archiving it is ezexe's own pick, never this session's judgement. {lead} Then end the turn "
                f"with `mcp__ccd_turn__wrap_up` whose question is \"Archive \"{title}\"?\", cut to fit, and whose "
                f"buttons are the replies \"{BUTTON_YES}\" and \"{BUTTON_NO}\". Archive nothing in this turn. "
                f"When ezexe's next message is \"{BUTTON_YES}\", archive exactly "
                + ("that session and those of its tree" if kids else "that session")
                + f" in that turn, and phi lets it through; on anything else leave it and say so.{out}")
    lines = "\n".join(f"- label \"{o['label']}\", description \"{o['description']}\"" for o in opts)
    n = len(ready)
    return (f"phi (p4-phi): {n} session{'s' if n != 1 else ''} this puppeteer controls {'are' if n != 1 else 'is'} "
            f"complete. Archiving {'them' if n != 1 else 'it'} is ezexe's "
            f"own pick, never this session's judgement. {lead} Then, before `mcp__ccd_turn__wrap_up`, put them to "
            f"ezexe as one quick select: one `AskUserQuestion` with `multiSelect` true, each option a session by "
            f"its full title, exactly these options"
            + (", with a last option \"None of them\"" if len(opts) == 1 else "") + f":\n{lines}\n"
            f"Archive none of them before ezexe has answered. Then archive exactly the sessions under the options "
            f"ezexe picked, and no other: ezexe's selection is the user action, and phi lets those through. Name "
            f"each one archived and each one left.{out}")


def picked(home, s, turn):
    """The session ids ezexe picked in this turn: the ids under each offered option whose label an answered
    AskUserQuestion of the turn carries, and the ids under the offered button when the turn's own message is that
    button's label."""
    turn = turn or {}
    out = list(relay.picked(home, s["sessionId"], turn.get("calls")))
    said = PHI.clean(turn.get("prompt")).strip(" .!\"'").lower()
    for o in s.get("archiveOffer") or []:
        if isinstance(o, dict) and o.get("button") and said == str(o.get("label") or "").lower():
            out += [i for i in o.get("ids") or [] if i not in out]
    return out


def waited_on(s):
    """The full titles of the controlled sessions a puppeteer may still be waiting on: each one the app has not
    archived that is working, has something open, or is not shown done."""
    out = []
    for e in controlled(s):
        state, _ = standing(e.get("store") or "", e["sessionId"])
        if state in ("working", "open", "not shown done"):
            out.append(full_title(e["sessionId"]))
    return out


# --- a boundary, and the notice that is a button -------------------------------------------------------------------------

def handed_chars(home, s):
    """The characters phi's hooks handed this session since its last compaction, from its own log."""
    since = str(s.get("compactedAt") or "")
    return sum(int(r.get("said") or 0) for r in PHI.read_rows(os.path.join(PHI.session_dir(home, s["sessionId"]),
                                                                           "log.jsonl"))
               if str(r.get("time") or "") >= since)


def boundary(home, s, store=""):
    """The notice a puppeteer is handed once a boundary, '' otherwise: a controlled tree has closed, or every
    controlled session is idle with no request waiting. Never while a controlled session waits on the puppeteer's
    answer. The caller saves what was told."""
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
    pick = offer_text(home, s, button=not (newly or idle)) if ready else ""    # #63: archived by ezexe's pick
    if pick and not (newly or idle):
        return pick                                # a tree is complete while another works: no boundary yet
    why = (f"the tree of \"{full_title(newly[0])}\" has closed" if newly else
           "every controlled session is idle and no request is waiting")
    path = board_path(home, s["sessionId"])
    past = (f" phi has handed this session {chars} characters since its last compaction, past the ceiling of {top}."
            if chars >= top else "")
    second = ("the app's `new_session` action, which starts the successor puppeteer from the board; its brief is "
              f"the board's path and `{PHI.commands()} controls --from {s['sessionId']}`, and this session then runs "
              f"`{PHI.commands()} controls --hand <its sessionId>`"
              if int(s.get("compactions") or 0) >= COMPACTIONS else "\"Later\"")
    return ((pick + "\n\n" if pick else "") +
            f"phi (p4-phi): a boundary: {why}.{past} When this turn's relays are done, keep what is not yet on the "
            f"board, {path}, with `{PHI.commands()} note`. Then read the context level with "
            f"`mcp__ccd_session_mgmt__get_usage` on `\"self\"` and end the turn with `mcp__ccd_turn__wrap_up` whose "
            f"question is one short sentence with that level, such as \"Context is at 71%, auto-compact starts at "
            f"85%. Compact now?\", and whose buttons are \"Compact now\" and {second}. On \"Compact now\" answer "
            f"with one line only: `/compact keep the path of the puppeteer board, {path}, and read it first`. On "
            f"\"Later\" say nothing more.")


def compacted(home, s):
    """A puppeteer's session after a compaction: the count starts again, and its board's path comes first."""
    s["compactedAt"] = PHI.now()
    s["compactions"] = int(s.get("compactions") or 0) + 1
    s.pop("boundary", None)
    return (f"phi (p4-phi): this session is a puppeteer and its context was compacted. Read its board before "
            f"anything else: {board(home, s)}")


# --- a successor ------------------------------------------------------------------------------------------------------------

def hand(home, s, new):
    """The old puppeteer marks its hand-over to a fresh one."""
    new = PHI.safe_id(new)
    if new == s["sessionId"] or not PHI.app_record(new):
        raise ValueError(f"the app holds no record of a successor {new}")
    s["handedTo"] = {"sessionId": new, "time": PHI.now()}
    PHI.save_session(home, s)
    return (f"handed over to \"{full_title(new)}\" ({new}): it runs `controls --from {s['sessionId']}`, then keeps "
            f"this session's outcome with `note` and archives it")


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
            f"{'s' if n != 1 else ''} from \"{full_title(old, o)}\" ({old})")


# --- requests through the puppeteer ---------------------------------------------------------------------------------------

def request_call(r):
    """The exact start_session input for a request addressed to a puppeteer: a new top session in the
    requester's environment."""
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
                            r["title"] + "\n" + r["brief"])     # #61


def requests_text(home, s):
    """The requests addressed to this puppeteer, handed at a turn ezexe began: each with its exact call."""
    rows = requests_for(s)
    if not rows:
        return ""
    lines = [f"- {r['id']} \"{r['title']}\" from \"{full_title(r['requester'])}\" ({r['requester']}), to be filed in "
             f"{filing(r['store'], s)}: `mcp__ccd_session__start_session` with "
             f"{json.dumps(request_call(r), ensure_ascii=False)}" for r in rows]
    return ("phi (p4-phi): controlled sessions ask this puppeteer for new top sessions. This turn ezexe began, so "
            "for each either start it with exactly the call given and then file it with "
            "`mcp__ccd_sidebar__move_sessions` where named, never in the puppeteers' section, or decline it with "
            f"`{PHI.commands()} controls --decline <request id> \"<why>\"` and one line to ezexe. phi records a "
            "started one as controlled at this session's next hook:\n" + "\n".join(lines))


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
    return f"declined {rid} \"{row.get('title')}\": its requester is told at its next message"


def answers_text(home, s):
    """What became of a session's requests to its puppeteer, read from the puppeteer's record: a declined one is
    closed in this session's own store and named once."""
    held = s.get("puppeteer") if isinstance(s.get("puppeteer"), dict) else {}
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
    _ = held
    return ("phi (p4-phi): " + "; ".join(lines) + ". Start no session for it.") if lines else ""


# --- a go to a waiting writer (#62) --------------------------------------------------------------------------------------

def go_text(home, s, target, message=""):
    """A puppeteer's message to a session it controls -> one line when another controlled session, or a session in
    its tree, still holds a file in that writer's set: the holder by full title, and what frees the files. ''
    when nothing is held or the pair was warned of already. The set is the one the message declares on a
    `Files:` line, else the one the target declared."""
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
    names = "; ".join(f"\"{title}\" ({sid}) holds {', '.join(hit[:4])}" for sid, title, hit in held[:4])
    return (f"phi (p4-phi): this go to \"{full_title(target)}\" is early: {names}, and no two sessions write the "
            f"same file at once (ezexe/p4#48). Hold the go until that session reports done, or have it release what "
            f"it has landed with `{PHI.commands()} files --release` or `{PHI.commands()} files <the paths it still "
            f"writes>` first. Said once for this pair.")


# --- routing down ----------------------------------------------------------------------------------------------------------

def route_down(s, words_):
    """ezexe's message to a puppeteer that a controlled session's topic covers -> the line that sends it there."""
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
    return (f"phi (p4-phi): this message reads as work on the topic \"{full_title(sid)}\" ({sid}) orchestrates. If so, "
            f"do not do it here and start no child for it: send that session one message with SendMessage, holding "
            f"ezexe's words, a line `Files: <paths>` and what done looks like, and telling it to brief and start a "
            f"child session of its own for it. Keep it on the board with `{PHI.commands()} note \"<what was sent "
            f"and to whom>\" --source \"<the message>\" --kind waiting` until its report comes. A topic no "
            f"controlled session covers gets a new top session that this puppeteer starts and files.")
