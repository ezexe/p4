"""upkeep.py: the upkeep of a session tree, which a session that started others keeps by itself.

`phi.upkeep` in the store's p4.json turns it on for a project, off by default, and `phi.py upkeep on` or `off` sets it,
since a session writes nothing under `.claude` with its own tools. With it off this module hands nothing and keeps
nothing. With it on, beside every message a session that started others gets, and at the turn the hooks module starts
for it, p4-phi hands the exact acts that are due for those sessions, and the setting is ezexe's standing word for each:

  archive      a started session that is finished, with no open step, no background task and its last report handed,
               and whose commits are all on its repository's default branch on the remote, is named by its whole
               title with the exact archive call. One whose work is not landed gets the landing line first.
               The archive is the app's own tool: desktop.md, "Work across sessions", has Claude "archive a session",
               and says "You get an approval card before Claude archives a session, except in Auto mode and Bypass
               permissions mode". So nothing archives here: the line names the call, and the settings keeper takes
               its own ask rule on the tool out, which made the app ask in those two modes as well.
  follow       what a finished worker's report lists as found and not fixed, or as left, is kept as open items in
               upkeep.json in the orchestrator's folder. Each goes back to that worker by message while it is live
               and its context is short, and otherwise to a successor, and it closes only on a commit on the default
               branch that names it, on a note that says why it is left, or on ezexe's word. Every open item is
               listed at every turn.
  waits        a step the orchestrator said waits on another session is kept with that session, by its own task
               list's words or by `phi.py upkeep wait`, and is handed as due once that session's work is on the
               default branch.
  leftovers    after an archive, that session's worktree and branch are named for removal where the worktree is
               clean and the branch merged, by `git worktree remove` with no force and `git branch -d`, never `-D`,
               and so is the worktree of a subagent whose branch is merged. The app removes the worktree it made
               itself: the archive tool's text says "Archiving stops the session's process and (by default) cleans up
               its worktree", and desktop.md, "Keep uncommitted changes when a session is archived", that a worktree
               with changes "stays on disk" for about 30 days. Claude Code removes a subagent's worktree "when the
               subagent finishes without changes" and sweeps one with changes once it is older than
               `cleanupPeriodDays`, worktrees.md, "Clean up subagent and background-session worktrees". What neither
               does is the rest: the branch, a worktree a session made with `git worktree add`, and a merged
               subagent worktree before that sweep. Anything dirty or unmerged is named to ezexe once and left.

No act runs in this module's own process. git is asked only what is true, and the session runs each command, so its
own permission rules hold for every one: phi.py is allowed by p4's allow rule, and a removal run inside it would pass
those rules by.

The app refuses a new start on a turn no person began. Its own instructions to a desktop session, "Starting other
sessions", say "On a turn that another session's message or an automated event started, the app refuses a start:
propose instead", and the start tool's text says of `own_initiative` that "the user sees a card and nothing runs
until they start it". A message to a live session goes through on any turn. So on such a turn a step or an item that
wants a new session goes by message to a live worker whose task covers it, and otherwise is shown as the app's card
with one line to ezexe.

The setting is also ezexe's standing word that such a start is no card: it is a scripted Claude Code run in a tab of
the app's Terminal panel, a terminal worker, which "a worker in the Terminal panel" below builds and removes. The
card stays where the session runs in a permission mode that asks, where its folder is in no git repository with a
default branch on a remote, and with the setting off.

When every started session is idle and an act is due that no turn was started for yet, `wake` answers the prompt of a
turn the hooks module starts. Each such turn counts in upkeep.json, against `phi.keep_going_max` together with the
module's other wakes, until ezexe's own message begins a turn, and no act starts a second one, so two sessions that
answer each other never wake each other without end.
"""

import hashlib
import os
import re
import time

import p4conf
import plans
import relay
import store as st

PHI = None                       # phi.py's own module, handed over when phi.py imports this one

FILE = "upkeep.json"             # in a session's folder: its open items, its waits and what it was told
ARCHIVE = "mcp__ccd_session_mgmt__archive_session"
START = "mcp__ccd_session__start_session"
MARK = plans.UPKEEP_MARK         # opens the prompt of a turn the hooks module starts for upkeep
TRIES = 3                        # turns one archive call is handed before p4-phi leaves it
ITEMS = 12                       # items taken from one report
ITEM_CHARS = 400                 # of one item
OPEN_MOST = 60                   # open items one session keeps
FIT_WORDS = 3                    # content words a step shares with a live worker's task before it goes there
# Words that make no fit: the words every brief of this project carries, and everyday words no task has to itself.
EVERYDAY = plans.SIBLING_STOP | st.COMMON | frozenset("own owns owned itself".split())
NO_ASK = ("auto", "bypassPermissions")   # the permission modes the app archives in without its card


def on():
    """True when the project of the running hook or command has `phi.upkeep` on."""
    return bool(PHI is not None and getattr(PHI, "UPKEEP", False))


def now():
    return time.strftime("%Y-%m-%d %H:%M")


def path(home, sid):
    return os.path.join(relay._dir(home, sid), FILE)


def load(home, sid):
    d = relay._read_json(path(home, sid))
    for k, kind in (("items", list), ("waits", list), ("named", list), ("wokeFor", list), ("terminals", list),
                    ("tried", dict),
                    ("scanned", dict), ("swept", dict), ("mains", dict)):
        if not isinstance(d.get(k), kind):
            d[k] = kind()
    return d


def save(home, sid, d):
    relay._write_json(path(home, sid), d)


def set_on(store, flag):
    """`phi.upkeep` written to the store's p4.json, and the settings keeper run for the project the store sits in, so
    its ask rule on the archive tool goes or comes back at once. Returns the lines to print."""
    was = p4conf.upkeep_on(store)
    p4conf.set_key(store, "phi.upkeep", bool(flag))
    out = [f"phi.upkeep is {'on' if flag else 'off'} in {p4conf.fwd(p4conf.path(store))}"
           + ("" if was != bool(flag) else ", as it was")]
    project = os.path.dirname(os.path.dirname(os.path.abspath(store)))
    if os.path.basename(os.path.dirname(os.path.abspath(store))) == ".claude":
        kept = p4conf.keep_settings(project, p4=store)
        asks = p4conf._get(p4conf.read_json(kept["file"]) or {}, p4conf.ASK_KEY)
        held = isinstance(asks, list) and ARCHIVE in asks
        out.append(f"{p4conf.fwd(kept['file'])} holds "
                   + (f"an ask rule on `{ARCHIVE}`" + ("" if not flag else ", which is not p4's own: p4 takes out "
                                                       "only the entry it wrote") if held
                      else f"no ask rule on `{ARCHIVE}`"))
    out.append("With it on, a session that started others is handed the archive call of each finished, landed "
               "session, its open follow-through items, the steps whose wait is over and the leftovers on disk."
               if flag else "With it off, p4-phi hands none of the upkeep acts and keeps the archive ask rule.")
    return out


# --- what git says ----------------------------------------------------------------------------------------------------

_DEFAULT = {}                    # a repository's folder to its default branch on the remote, for one process


def _out(cwd, *args):
    r = relay._git(cwd, *args) if cwd and os.path.isdir(cwd) else None
    return r.stdout.strip() if r is not None and r.returncode == 0 else None


def default_ref(repo):
    """The default branch of the repository's remote as a ref, such as `origin/main`, '' when git names none:
    `origin/HEAD` as the clone or a fetch set it, else `origin/main` or `origin/master` when one is there."""
    if repo in _DEFAULT:
        return _DEFAULT[repo]
    ref = _out(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") or ""
    for name in ("origin/main", "origin/master") if not ref else ():
        if _out(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/{name}") is not None:
            ref = name
            break
    _DEFAULT[repo] = ref
    return ref


def on_default(repo, rev):
    """True when `rev` is on the remote's default branch as this clone last saw it, None when that cannot be told."""
    ref = default_ref(repo)
    if not ref or not rev:
        return None
    r = relay._git(repo, "merge-base", "--is-ancestor", rev, ref)
    return None if r is None or r.returncode not in (0, 1) else r.returncode == 0


def ahead(repo, rev):
    n = _out(repo, "rev-list", "--count", f"{default_ref(repo)}..{rev}") if default_ref(repo) else None
    return int(n) if n and n.isdigit() else 0


def dirty(tree):
    """How many changed or untracked files a worktree holds, None when git cannot say."""
    got = _out(tree, "status", "--porcelain")
    return None if got is None else len([x for x in got.splitlines() if x.strip()])


def main_of(tree):
    main, found = p4conf.main_root(tree) if tree else ("", False)
    return main if found else ""


def linked(tree):
    """True for a linked worktree: a checkout whose repository's main checkout is another folder."""
    main = main_of(tree)
    return bool(main) and relay.norm(os.path.realpath(main)) != relay.norm(os.path.realpath(tree))


def locked_trees(main):
    """The worktrees of a repository git holds locked, as Claude Code locks a running agent's."""
    out, cur = set(), ""
    for line in (_out(main, "worktree", "list", "--porcelain") or "").splitlines():
        if line.startswith("worktree "):
            cur = relay.norm(line[9:].strip())
        elif line.startswith("locked") and cur:
            out.add(cur)
    return out


def trees_of(home, sid, s):
    """The checkouts a session worked in, by its turns' heads and the app's record of its worktree, each as a dict:
    `path`, `first` and `last`, the heads its first and latest turn read there, `linked`, True for a linked worktree,
    `own`, True for the worktree the app made for it, `there`, True while the folder is on disk, and `branch`."""
    rec = PHI.app_record(sid) if str(sid).startswith("local_") else {}
    own = relay.norm(str(rec.get("worktreePath") or ""))
    seen = {}
    for r in relay._rows(os.path.join(relay._dir(home, sid), "turns.jsonl")):
        for h in (r.get("delta") or {}).get("heads") or []:
            repo, _, sha = str(h).rpartition(" ")
            where, _, branch = repo.rpartition("@")
            if not where:
                continue
            t = seen.setdefault(relay.norm(where), {"path": where, "first": sha, "branch": branch})
            t["last"], t["branch"] = sha, branch or t["branch"]
    if own and own not in seen:
        seen[own] = {"path": str(rec.get("worktreePath")), "first": "", "last": "", "branch": ""}
    out = []
    for key, t in seen.items():
        there = os.path.isdir(t["path"])
        # a folder that is gone is read as a worktree that was removed: `lost` then asks git which repository, if
        # any, still holds its branch
        t.update(there=there, own=key == own, linked=linked(t["path"]) if there else True)
        if there and t["linked"]:
            t["branch"] = relay.branch_of(sid, s, t["path"]) or t["branch"]
        elif key == own:
            t["branch"] = str(rec.get("branch") or t["branch"] or "")
        out.append(t)
    return out


def landing(home, sid, s):
    """Whether a session's work is landed, and what holds it where it is not: every commit of each worktree of its
    own is on the remote's default branch with nothing uncommitted there, and so is every commit it made in a
    checkout it shares. Returns (True or False, the reasons, its trees)."""
    why, trees = [], trees_of(home, sid, s)
    for t in trees:
        where = t["path"].replace("\\", "/")
        if t["linked"] and t["there"]:
            n = dirty(t["path"])
            if n is None:
                why.append(f"git could not read its worktree {where}")
                continue
            if n:
                why.append(f"its worktree {where} holds {n} uncommitted change{'s' * (n != 1)}")
            got = on_default(t["path"], "HEAD")
            if got is None:
                why.append(f"no default branch of a remote is known in {where}")
            elif not got:
                k = ahead(t["path"], "HEAD")
                why.append(f"{k or 'some'} commit{'s' * (k != 1)} of `{t['branch'] or 'its branch'}` in {where} "
                           f"{'are' if k != 1 else 'is'} not on {default_ref(t['path'])}")
        elif t["there"] and t["first"] and t["last"] and t["first"] != t["last"]:
            if on_default(t["path"], t["last"]) is False:
                why.append(f"its commit {t['last']} in {where} is not on {default_ref(t['path'])}")
    return not why, why, trees


# --- which sessions, and where each stands ----------------------------------------------------------------------------

def started(home, sid):
    """Each session this one started that the app has not archived, by its id."""
    return {k: v for k, v in sorted(relay._sessions(home).items())
            if relay._parent(v) == sid and not v.get("archived") and not relay.archived_in_app(v)}


def archived(home, sid):
    """Each session this one started that the app has archived, or holds no record of any more."""
    return {k: v for k, v in sorted(relay._sessions(home).items())
            if relay._parent(v) == sid and (v.get("archived") or relay.archived_in_app(v))}


def working(home, sid):
    return PHI.puppeteer.working(home, sid)


def finished(home, sid, s):
    """True when a started session's work is over by p4-phi's records: a turn of it ended and none runs, its last
    turn was shown done, its task list holds steps and none is open, or p4-phi counts it as archived already, and no
    session under it still works or holds an open step."""
    turns = relay._rows(os.path.join(relay._dir(home, sid), "turns.jsonl"))
    if not turns or working(home, sid):
        return False
    steps = plans.load(home, sid).get("steps") or []
    still = [x for x in steps if x.get("status") != "completed"]
    over = bool(turns[-1].get("done")) or (bool(steps) and not still) or bool(s.get("doneRetired") or s.get("stale"))
    if not over or still:
        return False
    for k, ks in relay._sessions(home).items():
        if k != sid and sid in PHI.chain_of(home, k) and not ks.get("archived") and not relay.archived_in_app(ks) \
                and (working(home, k) or plans.open_steps(home, k)):
            return False
    return True


def unread(home, s):
    """The sessions whose latest report this session has not been handed yet."""
    seen = s.get("reportsSeen") if isinstance(s.get("reportsSeen"), int) else 0
    return {r["sessionId"] for r in PHI.latest_reports(PHI.load_reports(home, s["sessionId"])[seen:])}


def title(sid, s=None):
    import book
    return book.title(sid, s) or str(sid)


def short_context(home, sid, store=""):
    """True while a session's context is short: Claude Code's last measure of it, which the hooks module keeps in
    usage.json, reads under `phi.clear_at` percent, or no measure is kept."""
    pct = ((PHI.usage_of(home, sid) or {}).get("context") or {}).get("percent")
    return pct is None or pct < PHI.controls.clear_at(store)


def live(sid, s):
    """True while the app still runs a session: it holds a record of it and has not archived it."""
    return not s.get("archived") and not relay.archived_in_app(s)


def fit(home, sid, text, store="", skip=()):
    """The live session this one started whose task covers `text`, as (id, session), or ('', {}). A word of
    EVERYDAY counts for nothing, so a step fits on the names of a session's files and the words of its task alone."""
    said = plans.words(text) - EVERYDAY
    best = ("", {}, 0)
    for k, ks in started(home, sid).items():
        if k in skip or not short_context(home, k, store):
            continue
        own = " ".join([str(ks.get("task") or "")] + [str(x) for x in ks.get("fileSet") or []])
        n = len(said & plans.words(own))
        if n >= FIT_WORDS and n > best[2]:
            best = (k, ks, n)
    return best[0], best[1]


# --- the report's own list of what it left ----------------------------------------------------------------------------

LEFT = (r"(?:still\s+)?found\s+(?:and|but)\s+not\s+fixed|not\s+fixed|findings\s+left\s+open|"
        r"left\s+(?:open|alone|undone|unfixed|for\s+later)|left(?=\s*(?:\*\*|__)?\s*(?::|$))|"
        r"what\s+is\s+(?:still\s+)?left|still\s+open|open\s+items?|follow[- ]?ups?|"
        r"not\s+(?:done|verified|checked)(?:\s+live)?|could\s+not\s+(?:verify|check|fix|finish)")
# A list of what is left opens with a heading that says so, or with a label that ends in a colon: prose that only
# holds the words, such as "we left the file as it was", opens none.
HEADING = re.compile(r"^\s*#{1,6}\s+(?:\*\*|__)?\s*(?:" + LEFT + r")\b[^\n]{0,60}$", re.I)
LABEL = re.compile(r"^\s*(?:[-*]\s+)?(?:\*\*|__)?\s*(?:" + LEFT + r")\b[^:\n.]{0,60}?(?:\*\*|__)?\s*:\s*(?:\*\*|__)?"
                   r"\s*(?P<rest>.*)$", re.I)
BULLET = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*\S)\s*$")
ANY_HEAD = re.compile(r"^\s*#{1,6}\s+\S")
NONE = re.compile(r"^\W*(?:none|nothing|n/?a|no (?:open )?items?)\W*$", re.I)


def left_of(text):
    """What a report lists as found and not fixed, or as left: the bullets under a heading or a label that says so,
    and the words after such a label on its own line. At most ITEMS, each cut to ITEM_CHARS."""
    out, lines, k = [], str(text or "").splitlines(), 0

    def keep(x):
        x = " ".join(re.sub(r"\*\*|__", "", x).split())
        if len(x) >= 8 and not NONE.match(x) and x not in out:
            out.append(PHI.cut(x, ITEM_CHARS) if PHI else x[:ITEM_CHARS])
    while k < len(lines):
        label, heading = LABEL.match(lines[k]), HEADING.match(lines[k])
        k += 1
        if not label and not heading:
            continue
        if label and label.group("rest").strip():
            keep(label.group("rest"))
            continue
        blank = 0
        while k < len(lines):
            b = BULLET.match(lines[k])
            if b and not LABEL.match(lines[k]):
                keep(b.group(1))
                blank = 0
            elif not lines[k].strip():
                blank += 1
                if blank > 1:
                    break
            elif ANY_HEAD.match(lines[k]) or LABEL.match(lines[k]) or not lines[k].startswith((" ", "\t")):
                break
            k += 1
    return out[:ITEMS]


def item_id(child, text):
    return "it-" + hashlib.sha1(f"{child} {' '.join(sorted(plans.words(text)))}".encode("utf-8")).hexdigest()[:8]


def scan(home, sid, d):
    """The items of each finished started session's latest report, taken into `d` once for that turn. True when one
    is new."""
    new = False
    rows = {r["sessionId"]: r for r in PHI.latest_reports(PHI.load_reports(home, sid))}
    for k, ks in relay._sessions(home).items():
        row = rows.get(k)
        turn = row.get("turn") if row and isinstance(row.get("turn"), dict) else {}
        mark = f"{turn.get('id')}@{turn.get('time')}"
        if relay._parent(ks) != sid or not turn or d["scanned"].get(k) == mark or not finished(home, k, ks):
            continue
        d["scanned"][k] = mark
        new = True
        found = turn.get("left") if isinstance(turn.get("left"), list) else left_of(turn.get("report"))
        for text in [str(x) for x in found][:ITEMS]:
            iid = item_id(k, text)
            if any(i.get("id") == iid for i in d["items"]):
                continue
            d["items"].append({"id": iid, "from": k, "title": title(k, ks), "text": text, "time": now(),
                               "turn": str(turn.get("id") or "")})
    open_ = [i for i in d["items"] if not i.get("closed")]
    for i in open_[:-OPEN_MOST]:
        i["closed"] = {"how": "dropped", "why": f"more than {OPEN_MOST} open items", "time": now()}
    return new


def landed_ids(home, sid, d):
    """Closes each open item or wait whose id a commit on the remote's default branch names, in a repository the
    session that left it worked in. True when one closed."""
    open_ = [i for i in d["items"] + d["waits"] if not i.get("closed")]
    if not open_:
        return False
    repos, closed = {}, False
    for i in open_:
        k = i.get("from") or i.get("on") or ""
        for t in trees_of(home, k, relay._session(home, k)) if k else []:
            if t["there"]:
                repos.setdefault(main_of(t["path"]) or t["path"], t["path"])
    for tree in repos.values():
        ref = default_ref(tree)
        got = _out(tree, "log", "-200", "--format=%h%x1f%B%x1e", "-E", "--grep=(it|wt)-[0-9a-f]{8}", ref) if ref \
            else None
        for rec in (got or "").split("\x1e"):
            sha, _, body = rec.strip().partition("\x1f")
            for i in open_:
                if sha and not i.get("closed") and i["id"] in body:
                    i["closed"] = {"how": "commit", "commit": sha, "time": now()}
                    closed = True
    return closed


def close(home, s, iid, commit="", note="", ezexe="", cwd=""):
    """Closes an open item or wait by its id, on one of three grounds: a commit that is on the remote's default
    branch, a note that says why it is left, or ezexe's word, taken only in a turn ezexe's own message began. Returns
    the line to print."""
    sid = s["sessionId"]
    with relay.locked(path(home, sid)):
        d = load(home, sid)
        it = next((i for i in d["items"] + d["waits"] if i.get("id") == iid), None)
        if not it:
            raise ValueError(f"no open item or wait {iid}: `upkeep` alone lists them")
        if it.get("closed"):
            return f"{iid} was closed already, by {it['closed'].get('how')}"
        if commit:
            repo = cwd or os.getcwd()
            if on_default(repo, commit) is not True:
                raise ValueError(f"{commit} is not on {default_ref(repo) or 'a default branch of a remote'} in {repo}: "
                                 f"an item closes on a landed commit, so land it first, or run this from its "
                                 f"repository")
            it["closed"] = {"how": "commit", "commit": commit, "time": now()}
        elif note:
            if len(" ".join(note.split())) < 12:
                raise ValueError("a note says why it is left, in a sentence")
            it["closed"] = {"how": "note", "why": " ".join(note.split())[:400], "time": now()}
            PHI.note_add(home, sid, f"left: {it.get('text') or it.get('step')} ({iid}). Why: {it['closed']['why']}",
                         "phi.py upkeep close", "left")
        elif ezexe:
            if s.get("turnBy") != "user":
                raise ValueError("ezexe's word closes an item only in a turn ezexe's own message began, and this "
                                 "turn began with another session's message or an event")
            it["closed"] = {"how": "ezexe", "why": " ".join(ezexe.split())[:400], "time": now()}
        else:
            raise ValueError("name what closes it: --commit <sha>, --note \"<why it is left>\" or --ezexe "
                             "\"<ezexe's words>\"")
        save(home, sid, d)
    return f"{iid} closed by {it['closed']['how']}"


def wait(home, s, text, on_sid):
    """Keeps a step this session said waits on another session, with that session. Returns the line to print."""
    sid, on_sid = s["sessionId"], PHI.safe_id(on_sid)
    if relay._parent(relay._session(home, on_sid)) != sid:
        raise ValueError(f"{on_sid} is no session this one started")
    text = " ".join(str(text or "").split())
    if len(text) < 12:
        raise ValueError("say the step that waits, in a sentence")
    wid = "wt-" + hashlib.sha1(f"{on_sid} {text}".encode("utf-8")).hexdigest()[:8]
    with relay.locked(path(home, sid)):
        d = load(home, sid)
        if not any(w.get("id") == wid for w in d["waits"]):
            d["waits"].append({"id": wid, "step": text[:ITEM_CHARS], "on": on_sid, "time": now()})
            save(home, sid, d)
    return (f"kept as {wid}: it is handed as due once the work of \"{title(on_sid)}\" `{on_sid}` is on its "
            f"repository's default branch")


# --- a step that falls due when no session is open, by Claude Code's own scheduled runs ---------------------------------
# A step that waits on a time, and not on a session, may fall due while no session is open, and then nothing of
# p4-phi runs: its hooks and its module live in a session. Claude Code has runs that start with no session open, and
# p4-phi builds none of its own. scheduled-tasks.md, "Compare scheduling options", sets three beside each other: a
# cloud scheduled task runs on "Cloud, Anthropic-managed by default", needs neither the machine on nor an open
# session, and has "No (fresh clone)" for access to local files; a Desktop scheduled task runs on "Your machine",
# needs no open session and has local files; and `/loop` needs an open session, so it is no answer here. "Use cloud
# tasks for work that should run reliably without your machine. Use Desktop tasks when you need access to local
# files and tools."
# So a step that needs only the repository is a cloud scheduled task's: routines.md, "Run `/schedule` in any session
# to create a scheduled task conversationally. You can also pass a description directly", and "Each repository is
# cloned at the start of a run." And a step that needs the project's local store, which no clone holds, is a Desktop
# scheduled task's: desktop-scheduled-tasks.md, "Tasks only run while the desktop app is running and your computer
# is awake", and "You can also ask Claude in any Desktop session to set the schedule", which is the tool
# DESKTOP_TASK there.
# Making either starts sessions later, so the making is ezexe's, in Claude Code's own flow, and p4-phi makes none:
# `later` keeps the step and prints the command with the prompt written. `/schedule` asks ezexe for the repository
# and confirms the time before it saves. The desktop tool's own text says "an approval prompt may or may not appear
# depending on the user's permission settings, so don't rely on it as the confirmation step", so its line asks for
# ezexe's yes first.
SCHEDULE = "/schedule"
DESKTOP_TASK = "mcp__scheduled-tasks__create_scheduled_task"
RUN_ENDS = ("No session is open while this runs, and it knows nothing of the session that asked for it, so the step "
            "is whole in these words. End with one line on what was done and one on what is left.")


def run_prompt(step, folder=""):
    """The prompt of a scheduled run for a step, on one line: the step as the session wrote it, the folder whose
    store it needs where it needs one, and how the run ends."""
    where = f" Work in the folder {folder}, whose `.claude/p4` is the project's store." if folder else ""
    return f"{step.rstrip('.')}.{where} {RUN_ENDS}"


def later(home, s, text, when, local=False):
    """Keeps a step this session said falls due at a time, when no session may be open, as a wait with `at`, and
    returns the lines to print: which scheduled run of Claude Code fits it, and the command with the prompt written,
    for ezexe to make. With `local` the step needs the project's local store or other files of this machine."""
    sid = s["sessionId"]
    text, when = " ".join(str(text or "").split()), " ".join(str(when or "").split()).rstrip(",.")
    if len(text) < 12:
        raise ValueError("say the step that waits, in a sentence")
    if not when:
        raise ValueError("say when the step falls due, as `--at \"tomorrow at 9am\"` or `--at \"every weekday at 7am\"`")
    folder = spelled(main_of(str(s.get("cwd") or "")) or str(s.get("cwd") or "")) if local else ""
    wid = "wt-" + hashlib.sha1(f"{when} {text}".encode("utf-8")).hexdigest()[:8]
    with relay.locked(path(home, sid)):
        d = load(home, sid)
        if not any(w.get("id") == wid for w in d["waits"]):
            d["waits"].append({"id": wid, "step": text[:ITEM_CHARS], "at": when[:120], "local": bool(local),
                               "time": now()})
            save(home, sid, d)
    prompt = run_prompt(text[:ITEM_CHARS], folder)
    closes = (f"Close it with `{PHI.commands()} upkeep close {wid} --note \"<what ezexe made or said>\"` once ezexe "
              f"has answered.")
    if local:
        return "\n".join([
            f"kept as {wid}: a step that falls due when no session is open is a scheduled run's, and this one needs "
            f"the project's local store, which a cloud run's fresh clone does not hold. So it is a Desktop scheduled "
            f"task's, which runs on this machine with its files while the desktop app is open and the computer is "
            f"awake. Making one starts sessions later, so it is ezexe's to make and p4-phi makes none: put it to "
            f"ezexe once, by the app's own question, with the words below as the task's instructions. On ezexe's yes "
            f"alone, make it with `{DESKTOP_TASK}`, those words as its `prompt` and \"{when}\" as its schedule, or "
            f"leave ezexe to make it under Scheduled, New task, with Only on this computer on and the folder "
            f"{folder}.",
            prompt, closes])
    return "\n".join([
        f"kept as {wid}: a step that falls due when no session is open is a scheduled run's, and this one needs only "
        f"the repository. So it is a cloud scheduled task's, which works in a fresh clone on Anthropic's cloud with "
        f"this machine on or off. Making one starts sessions later, so it is ezexe's to make and p4-phi makes none: "
        f"give ezexe the command below to type, as it stands and in a fenced block of its own, and do not run it "
        f"yourself. Claude Code's own flow then asks ezexe for the repository and confirms the time before it saves "
        f"the task.",
        f"{SCHEDULE} {when}, {prompt}", closes])


WAITS = re.compile(r"\b(?:a?wait\w*|after|once|when|until|blocked\s+(?:on|by)|depends?\s+on|needs?)\b", re.I)


def plan_waits(home, sid, kids):
    """The open steps of a session's own task list that say they wait on a session it started, named in the step by
    its id, by the short name the app gave it or by its whole title: each as (step, the session's id)."""
    out = []
    for x in plans.load(home, sid).get("steps") or []:
        text = str(x.get("content") or "")
        if x.get("status") == "completed" or not WAITS.search(text):
            continue
        low = text.lower()
        for k, ks in kids.items():
            rec = PHI.app_record(k) if str(k).startswith("local_") else {}
            sp = rec.get("spawnedFrom") if isinstance(rec.get("spawnedFrom"), dict) else {}
            names = [str(k), str(sp.get("name") or ""), title(k, ks)]
            if any(len(n) >= 6 and n.lower() in low for n in names):
                out.append((x, k))
                break
    return out


# --- the acts ---------------------------------------------------------------------------------------------------------

def spelled(p):
    """A folder as the file system spells it, with forward slashes: a turn's heads keep it case folded."""
    return (os.path.realpath(p) if os.path.isdir(p) else str(p)).replace("\\", "/")


def run_from(home, s, main, but=""):
    """A checkout of the repository whose main checkout is `main` that a git command of this session runs from: one
    the session itself works in, else that main checkout."""
    for t in trees_of(home, s["sessionId"], s) + [{"path": str(s.get("cwd") or ""), "there": True}]:
        p = t["path"]
        if p and t.get("there") and os.path.isdir(p) and relay.norm(p) != relay.norm(but) \
                and relay.norm(main_of(p) or "") == relay.norm(main):
            return spelled(p)
    return spelled(main)


# Where the session that reads a removal stands decides the git command it can run. worktrees.md, "How Claude Code
# enforces isolation": "While a session is isolated in a worktree, Claude Code blocks the tool calls the checks below
# define", among them "Git redirects: Claude Code blocks a Bash or Monitor command that redirects git into the main
# checkout. The redirect can come through `git -C`, `--git-dir`, a `GIT_DIR` or `GIT_WORK_TREE` variable, or a `cd`
# into the main checkout before running git." The same page, "What worktrees share with the main checkout": "git
# commands in a worktree write to the main repository's shared `.git` directory." So from a worktree of the repository
# `git worktree remove` and `git branch -d` reach it with no `-C`, and `-C` stays for a session in no worktree.
_TOP = {}                        # a folder to the checkout it lies in, for one process


def stand(home, s, main, but=""):
    """How the session that reads a line runs git on the repository whose main checkout is `main`, as (how, folder):
    ("-C", a checkout of it) where the session's own folder is no worktree, as run_from picks the checkout; ("in", a
    worktree of it) where its own folder is a linked worktree, that folder when it is of this repository, else a
    worktree of this repository the session itself works in, and git then runs there with no `-C`; ("", "") where
    its own folder is a worktree of another repository and it works in none of this one."""
    here = str(s.get("cwd") or "")
    if here not in _TOP:
        _TOP[here] = _out(here, "rev-parse", "--show-toplevel") or ""
    top = _TOP[here]
    if not top or not linked(top):
        return "-C", run_from(home, s, main, but=but)
    same = relay.norm(os.path.realpath(main))
    for p in [top] + [t["path"] for t in trees_of(home, s["sessionId"], s) if t.get("there")]:
        if os.path.isdir(p) and relay.norm(p) != relay.norm(but) and linked(p) \
                and relay.norm(os.path.realpath(main_of(p) or "")) == same:
            return "in", spelled(p)
    return "", ""


def git_of(how, folder, rest):
    """One git command of a removal with the folder it runs in: (the command, '' where it carries `-C`)."""
    return (f"git -C \"{folder}\" {rest}", "") if how == "-C" else (f"git {rest}", folder)


THEIRS = ("it is clean and merged, and its repository, {main}, is not the one this session's own worktree is of, so "
          "a session in that repository removes it, by {cmds} run there")


def cmds_text(cmds):
    """The commands of a removal as a line names them, each in backticks, with the worktree to run those in that
    carry no `-C`."""
    by = {}
    for c, folder in cmds:
        by.setdefault(folder, []).append(f"`{c}`")
    return "; ".join("; ".join(cs) + (f", run in `{folder}` with no `-C`, which Claude Code refuses from a worktree"
                                      if folder else "") for folder, cs in by.items())


def in_use(home, but=()):
    """The folders the sessions the app still runs work in, by p4-phi's records and the app's, without those of the
    sessions `but`."""
    out = set()
    for k, v in relay._sessions(home).items():
        if k in but or v.get("archived") or relay.archived_in_app(v):
            continue
        rec = PHI.app_record(k) if str(k).startswith("local_") else {}
        out |= {relay.norm(str(p)) for p in (v.get("cwd"), rec.get("cwd"), rec.get("worktreePath")) if p}
    return out


def nested(tree):
    """The checkouts inside a worktree that git ignores there, which a removal of the worktree would take along."""
    out = []
    for line in (_out(tree, "status", "--porcelain", "--ignored") or "").splitlines():
        if line.startswith("!! "):
            p = os.path.join(tree, line[3:].strip().strip('"').rstrip("/"))
            if os.path.isdir(p) and os.path.exists(os.path.join(p, ".git")):
                out.append(relay.norm(p))
    return out


def repos_of(home, s, gone="", kept=None):
    """The main checkouts a worktree that is gone from disk may have belonged to: the one upkeep.json kept for it
    while it was there, the one its nearest folder still on disk lies in, and those of the repositories this session
    and the sessions it started work in."""
    sid, out = s["sessionId"], {}
    paths = [str((kept or {}).get(relay.norm(gone)) or "")]
    up = os.path.dirname(gone) if gone else ""
    while up and not os.path.isdir(up) and os.path.dirname(up) != up:
        up = os.path.dirname(up)
    paths += [up, str(s.get("cwd") or "")] + [t["path"] for t in trees_of(home, sid, s)]
    for k, ks in relay._sessions(home).items():
        if relay._parent(ks) == sid:
            paths += [t["path"] for t in trees_of(home, k, ks)]
    for p in paths:
        main = main_of(p) if p and os.path.isdir(p) else ""
        if main:
            out.setdefault(relay.norm(main), main)
    return list(out.values())


def lost(home, s, t, branch, mains):
    """A worktree that is gone from disk, as the app's archive leaves one: the commands that delete its merged branch
    in the repository that holds its last commit, after `git worktree prune` where git still lists the folder, and
    what holds an unmerged one, as (the commands, None or (what, why))."""
    if not branch or not t.get("last"):
        return [], None
    for main in mains:
        if _out(main, "cat-file", "-e", f"{t['last']}^{{commit}}") is None:
            continue
        if _out(main, "show-ref", "--verify", f"refs/heads/{branch}") is None \
                or branch == default_ref(main).rpartition("/")[2]:
            return [], None
        if on_default(main, branch) is not True:
            return [], (f"`{branch}` in {spelled(main)}", f"its worktree is gone and it holds commits that are not on "
                                                          f"{default_ref(main) or 'a default branch'}")
        how, frm = stand(home, s, main)
        listed = any(line.startswith("worktree ") and relay.norm(line[9:].strip()) == relay.norm(t["path"])
                     for line in (_out(main, "worktree", "list", "--porcelain") or "").splitlines())
        rest = (["worktree prune"] if listed else []) + [f"branch -d {branch}"]
        if not how:
            return [], (f"`{branch}` in {spelled(main)}",
                        THEIRS.format(main=spelled(main), cmds=" and ".join(f"`git {r}`" for r in rest)))
        return [git_of(how, frm, r) for r in rest], None
    return [], None


def removals(home, s, trees, skip_own=False, but=(), kept=None):
    """The commands that remove the clean, merged worktrees among `trees` and delete their merged branches, each as
    git_of gives it for where this session stands; what is dirty or unmerged, or of a repository this session cannot
    run git on, each as (tree, why); and True when a tree was passed over because a session the app still
    runs works in it. The deepest folder comes first, and a worktree that holds another checkout goes only after
    that one. `skip_own` leaves the folder the app made, and what lies in it, to the app's own archive, and `but`
    names the sessions whose folders count as free. `kept` is upkeep.json's record of each worktree's main checkout,
    read for one that is gone and written for one that is there."""
    cmds, held, waits, going, used = [], [], False, set(), None
    own = [relay.norm(t["path"]) for t in trees if t["own"]] if skip_own else []
    for t in sorted(trees, key=lambda t: -len(t["path"])):
        if not t["linked"]:
            continue
        branch = t["branch"] if t["branch"] not in ("", "HEAD") else ""
        key = relay.norm(t["path"])
        if any(key == o or key.startswith(o + "/") for o in own):
            continue
        if not t["there"]:
            more, why = lost(home, s, t, branch, repos_of(home, s, t["path"], kept))
            cmds += more
            if why:
                held.append(why)
            continue
        tree, main = spelled(t["path"]), main_of(t["path"])
        if kept is not None and kept.get(key) != main:
            kept[key] = main
        used = in_use(home, but) if used is None else used
        if any(u == key or u.startswith(key + "/") for u in used):
            waits = True
            continue
        if key in locked_trees(main):
            held.append((tree, "git holds it locked, as Claude Code locks the worktree of an agent that still runs"))
            continue
        n, got = dirty(t["path"]), on_default(t["path"], "HEAD")
        if n or n is None or got is not True:
            held.append((tree, (f"it holds {n} uncommitted change{'s' * (n != 1)}" if n else
                                "git could not read it" if n is None else
                                f"`{branch or 'its branch'}` holds commits that are not on "
                                f"{default_ref(t['path']) or 'a default branch'}")))
            continue
        inner = [x for x in nested(t["path"]) if x not in going]
        if inner:
            held.append((tree, f"it holds another checkout, {inner[0]}, which a removal would take along"))
            continue
        how, frm = stand(home, s, main, but=t["path"])
        rest = [f"worktree remove \"{tree}\""]
        # the branch is held to the default branch by its own tip: a worktree can sit on a detached HEAD, and then
        # its branch is the one the app's record names, which the folder's HEAD says nothing of
        if branch and branch != default_ref(main).rpartition("/")[2] \
                and _out(main, "show-ref", "--verify", f"refs/heads/{branch}") is not None:
            if on_default(main, branch) is True:
                rest.append(f"branch -d {branch}")
            else:
                held.append((f"`{branch}` in {spelled(main)}", f"it holds commits that are not on "
                                                               f"{default_ref(main) or 'a default branch'}"))
        if not how:                                # another repository to this session: named once, and left
            held.append((tree, THEIRS.format(main=spelled(main), cmds=" and ".join(f"`git {r}`" for r in rest))))
            continue
        cmds += [git_of(how, frm, r) for r in rest]
        going.add(key)
    return cmds, held, waits


LEAVE = ("Each is git's own command with no force, and `-d` is never `-D`: where git refuses one, leave it and say "
         "so in one line.")


# A session that made no commit has nothing to land, so "every commit of it on the default branch" holds for it
# with no work behind the words, and "finished" is read off its task list alone. A probe is such a session: it waits
# for its next step from whoever drives it, and that need not be its starter. On 2026-11-19 the archive of a probe
# was handed to its starter three times as finished and landed while another session still drove it through a
# plugin's prompts. So the archive of a session with no commit of its own is handed only while nobody but its
# starter drives it: its latest turn that somebody's words began was not begun by another live session's message
# or by the prompt of a plugin other than p4-phi, whose own prompts wake a session and drive none.
PLUGIN_SAID = re.compile(r"\AThe ([\w.-]+) plugin sent a message:")
OWN_PLUGIN = "p4-phi"


def teller(by, origin, prompt):
    """Who sent the words that began a turn, kept on the turn's row as `from`: the sending session's id for another
    session's message, by the wrapper Claude Code puts around it, the plugin's name for a prompt a hooks module
    submitted, by the origin's `name` or the line Claude Code heads it with, and '' for ezexe's own words and for
    an event."""
    if by == "session":
        import rows
        return rows.sender_of(prompt)
    if by == "plugin":
        m = PLUGIN_SAID.match(str(prompt or "").lstrip())
        return str((origin or {}).get("name") or (m.group(1) if m else ""))
    return ""


def driver(home, sid, s):
    """Who but its starter drives a started session, as words for a line, '' for nobody: the sender of its latest
    turn that somebody's words began, where that is another live session of the tree or a plugin other than
    p4-phi."""
    starter = relay._parent(s)
    for r in reversed(relay._rows(os.path.join(relay._dir(home, sid), "turns.jsonl"))):
        by = r.get("by")
        if by == "plugin":
            m = PLUGIN_SAID.match(str(r.get("prompt") or "").lstrip())
            name = str(r.get("from") or (m.group(1) if m else ""))
            if name == OWN_PLUGIN:
                continue                           # p4-phi's own wake: the turn before says who drives it
            return f"the plugin {name}" if name else ""
        if by == "session":
            sender = str(r.get("from") or "")
            other = relay._session(home, sender) if sender and sender != starter else {}
            live = bool(other) and not other.get("archived") and not relay.archived_in_app(other)
            return f"\"{title(sender, other)}\" `{sender}`" if live else ""
        if by == "user":
            return ""
    return ""


COMMITS = ("commit", "cherry-pick", "revert", "merge")   # what the reflog says of a move that made a commit


def made_commits(trees):
    """True when a session made a commit of its own, so that its work can be read as landed or not: in a worktree
    of its own the reflog of `HEAD` names a commit, a cherry-pick, a revert or a merge, where a rebase or a pull
    onto a default branch that moved names none, and in a checkout it
    shares its first and latest turn read different heads. A worktree that is gone, or that git cannot read, counts
    as one with work in it."""
    for t in trees:
        if not t["there"]:
            return True
        if t["linked"]:
            log = _out(t["path"], "reflog", "show", "--format=%gs", "HEAD")
            if log is None or any(x.startswith(COMMITS) for x in log.splitlines()):
                return True
        elif t.get("first") and t.get("last") and t["first"] != t["last"]:
            return True
    return False


def archive_acts(home, s, d, hand):
    out, sid = [], s["sessionId"]
    told = unread(home, s)
    mode = str((PHI.app_record(sid) if sid.startswith("local_") else {}).get("permissionMode") or "")
    for k, ks in started(home, sid).items():
        if k in told or not finished(home, k, ks) or PHI.puppeteer.held_tasks(home, k):
            continue
        ok, why, trees = landing(home, k, ks)
        if ok and not made_commits(trees) and driver(home, k, ks):
            continue                               # nothing of it to land, and another still drives it
        name = f"\"{title(k, ks)}\" `{k}`"
        if not ok:
            flows = relay.push_workflows(t["path"] for t in trees if t["there"])
            run = (f"the checks its task named and the test files of the paths it touches, then the push, then "
                   f"the run of the repository's workflow {' and '.join(f'`{n}`' for n, _ in flows)} on the pushed "
                   f"commit read with `gh run watch <run id> --exit-status`") if flows else \
                "the full suite once on the commit being pushed, then the push"
            out.append((f"land:{k}", "land", True,
                        f"land first: {name} is finished and its work is not landed: {'; '.join(why)}. An "
                        f"uncommitted change is its own to commit, so ask it by `SendMessage` to `{k}`. A commit "
                        f"that is not on the default branch is landed as the push line says: its branch merged into "
                        f"the default branch, {run}. It is "
                        f"archived at the turn after."))
            continue
        key = f"archive:{k}"
        n = int(d["tried"].get(key) or 0)
        if n >= TRIES:
            continue
        if hand:
            d["tried"][key] = n + 1
        cmds, _, _ = removals(home, s, trees, skip_own=True, but=(k,), kept=d["mains"])
        after = (f" Once the call returns, remove what it leaves on disk: {cmds_text(cmds)}. {LEAVE}") if cmds else ""
        card = "" if mode in NO_ASK else (" This session does not run in auto or bypass permissions mode, so the "
                                          "app shows ezexe its approval card for the call: that card is the app's.")
        last = (f" This is the {TRIES}rd time p4-phi hands it: if the app refuses again, as it does for a session "
                f"that is pinned, open on screen or still working, tell ezexe so in one line, and p4-phi hands it "
                f"no more.") if n + 1 >= TRIES else ""
        out.append((key, "archive", True,
                    f"archive: {name} is finished and landed: no open step, no background task, its last report "
                    f"handed, and every commit of it on its repository's default branch on the remote. Call "
                    f"`{ARCHIVE}` with `session_id` `{k}` and `reason` \"finished and landed\" now.{card}{after}"
                    f"{last}"))
    return out


# --- a worker in the Terminal panel -----------------------------------------------------------------------------------
# With `phi.upkeep` on, a start the app refuses on a turn no person began is a scripted Claude Code run that the
# session types into a tab of the app's Terminal panel, in place of the card that waits on ezexe. Claude Code does
# every part of it, and this module only hands the files and the one line. The pages, read on 2026-11-19:
# - headless.md, "Start faster with bare mode": without `--bare`, "`claude -p` discovers and loads them as an
#   interactive session would", installed plugins among them, and bare mode binds no inbox, so the run is not bare
#   and its `--settings` file turns p4's two plugins off. They are off because the run's folder is a worktree
#   `--worktree` made, which a terminal session takes as its project, so p4's hooks would set up a second store
#   inside it, and because p4-phi knows a worker by the app's record of it, which a scripted run has none of.
# - cross-session-messaging.md, "Non-interactive sessions": "Claude Code binds an inbox socket for a `claude -p`
#   session like an interactive one", and "To let a `-p` worker take messages unattended, start it with
#   `crossSessionInbound` set to `accept` in its `--settings` value."
# - worktrees.md, "Start Claude in a worktree": the worktree is `.claude/worktrees/<name>/` at the repository's
#   root on the branch `worktree-<name>`, and "Non-interactive runs with `-p` skip the trust check, so `claude -p
#   --worktree` proceeds without it". "Clean up worktrees": such a run leaves "the lock it took on each one at
#   creation in place until a later session's stale-lock sweep releases it. To remove one, run `git worktree
#   remove`; if git refuses because the worktree is locked, run `git worktree unlock` on it first."
# - headless.md, "Auto-approve tools": "In a Manual mode `claude -p` run, a call that needs approval is denied unless
#   something approves it". So the run takes the session's own permission mode, and only where that is auto or
#   bypass permissions: a higher mode than the session's own is ezexe's to give.
# - goal.md and the probes of 0.11.60: a scripted run is gone when its turn ends, and `claude -p "/goal <condition>"`
#   keeps it running until the condition is met, so the prompt is that command with a condition that names the brief.
# The first such worker, started on 2026-11-19 with these two settings while ezexe's user settings turn both plugins
# on, heard no hook of either plugin, kept its `/goal`, bound an inbox, and held git's lock on its worktree with the
# reason `claude session <name> (pid <n>)`.
RUN = "mcp__terminal__run_in_terminal"
TABS = "mcp__terminal__list_terminal_tabs"
CLOSE_TAB = "mcp__terminal__stop_terminal_tab"
TERMINAL = "a worker in the Terminal panel"      # the words of a line that names one, which `form` is added for
FOLDER = "terminal-workers"                      # in the shared notes folder: each worker's brief, script and report
SETTINGS_FILE = "worker-settings.json"
WORKER_SETTINGS = ('{"crossSessionInbound": "accept", "enabledPlugins": {"p4-phi@' + p4conf.MARKET
                   + '": false, "p4-temportal@' + p4conf.MARKET + '": false}}')
# what a shell of a desktop session hands down, which a run started from it must not carry as its own identity
CARRIED = ("CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
           "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN")
LOCK_PID = re.compile(r"\(pid (\d+)\)")
WINDOWS = os.name == "nt"


def mode_of(sid):
    return str((PHI.app_record(sid) if str(sid).startswith("local_") else {}).get("permissionMode") or "")


def worker_name(text):
    """The name of the terminal worker for a step or an item, which names its worktree, its branch and its files."""
    return "upkeep-" + hashlib.sha1(" ".join(sorted(plans.words(text))).encode("utf-8")).hexdigest()[:8]


def terminal(home, s, text, d=None, hand=False):
    """The terminal worker that takes work the app refuses a start for, as (its name, the main checkout it starts
    in, what upkeep.json keeps of it or None), or None where the card stays: with the setting off, in a session whose
    permission mode asks, and in a folder of no repository with a default branch on a remote. With `hand` it is kept
    in `d`."""
    main = main_of(str(s.get("cwd") or "")) if on() and mode_of(s["sessionId"]) in NO_ASK else ""
    if not main or not default_ref(main):
        return None
    name = worker_name(text)
    kept = next((t for t in d["terminals"] if t.get("name") == name), None) if d is not None else None
    if hand and d is not None and kept is None:
        d["terminals"] = (d["terminals"] + [{"name": name, "main": spelled(main), "time": now(),
                                             "text": " ".join(str(text).split())[:ITEM_CHARS]}])[-OPEN_MOST:]
    return name, spelled(main), kept


def script_of(s, name, main, windows=None):
    """The start script of a terminal worker, as (its file's name, its lines, the line typed into the tab). `<folder>`
    stands for the folder the session writes the files in, which only the session knows. Its goal carries the
    review of the change, plans.REVIEW_PART, as a started session's goal does, where `phi.goal_review` is
    on: a terminal worker's work is a change that lands on the default branch."""
    windows = WINDOWS if windows is None else windows
    sid, sep = s["sessionId"], "\\" if windows else "/"
    here = main.replace("/", sep)
    who = re.sub(r"[^\w .,:#-]", " ", title(sid, s))        # no quote and no shell character in the prompt
    prompt = (f"/goal Carry out the brief in the file <folder>{sep}brief-{name}.md. This is met when every part of "
              f"that brief is on {default_ref(main)} with its proof shown in this conversation, or is written into "
              f"the note <folder>{sep}report-{name}.md as left with the reason, and one message with the outcome "
              f"has been sent with SendMessage to the session named {who}."
              + (" " + plans.REVIEW_PART if PHI.GOAL_REVIEW else ""))   # its work lands on the default branch
    run = (f"claude -p '{prompt}' --name {name} --permission-mode {mode_of(sid)} --worktree {name} "
           f"--settings '<folder>{sep}{SETTINGS_FILE}'")
    if windows:
        names = ", ".join(f"'{n}'" for n in CARRIED)
        return (f"start-{name}.ps1",
                [f"foreach ($n in {names}) {{ Remove-Item -Path ('Env:' + $n) -ErrorAction SilentlyContinue }}",
                 f"Set-Location '{here}'", run], f"& '<folder>\\start-{name}.ps1'")
    return f"start-{name}.sh", [f"unset {' '.join(CARRIED)}", f"cd '{here}'", run], f"sh '<folder>/start-{name}.sh'"


def form(home, s, d, said):
    """The lines after the acts `said` where one of them names a terminal worker to start: what the session writes
    and the one call that starts each, said once for all of them, with `<name>` for a worker's name. [] where none
    does."""
    todo = [t for t in d["terminals"] if f"`{t.get('name')}`" in said] if TERMINAL in said else []
    if not todo:
        return []
    sid, main, here = s["sessionId"], todo[0]["main"], spelled(str(s.get("cwd") or ""))
    script, lines, typed = script_of(s, "<name>", main)
    names = " and ".join(f"`{t['name']}`" for t in todo)
    return [f"{TERMINAL[0].upper()}{TERMINAL[1:]} is a scripted Claude Code run in a worktree of its own, which "
            f"`phi.upkeep` has this session start in place of the app's card. In this turn, write the files below "
            f"into the folder `{FOLDER}` of the shared notes folder the app named to this session, with that "
            f"folder's whole path for `<folder>` and the worker's name for `<name>`, make the one call for each "
            f"worker, and say in one line that it runs.",
            f"  `{SETTINGS_FILE}`, once for all of them, holds exactly `{WORKER_SETTINGS}`: the first has its "
            f"messages delivered with nobody at its keyboard, and the second keeps p4's hooks, which would set up a "
            f"second store in its worktree, out of it.",
            f"  `brief-<name>.md` holds the work's own words, what done looks like, the proof to show, that it works "
            f"in its own worktree, lands by a fast-forward push to the default branch and opens no pull request, and "
            f"that it reports twice: one message by `SendMessage` to the session named \"{title(sid, s)}\", and the "
            f"note `report-<name>.md` beside the brief.",
            f"  `{script}` holds these {len(lines)} lines, each whole on a line of its own: "
            + " ".join(f"line {i}: {x}" for i, x in enumerate(lines, 1)),
            f"  Then, for each of {names}, call `{RUN}` with `title` `<name>`, `cwd` `{here}`, this session's own "
            f"folder, and `command` `{typed}`: the tool types one literal line and refuses a variable read, a pipe "
            f"and a second line, so everything else is in the file. Its worktree is `{main}/.claude/worktrees/<name>` "
            f"and its branch `worktree-<name>`.",
            f"  Such a worker has no row in the sidebar, no Changes card and no archive, and the app shows no check "
            f"of it: its message, its note and `{TABS}`, which says whether a command still runs in its tab, are "
            f"what tell of it. Once its run has ended, upkeep hands the close of its tab and the removal of its "
            f"worktree and branch."]


def lock_pid(main, tree):
    """The process a locked worktree's reason names, as Claude Code writes it, 0 where it names none, and None where
    git holds no lock on it."""
    cur, key = "", relay.norm(tree)
    for line in (_out(main, "worktree", "list", "--porcelain") or "").splitlines():
        if line.startswith("worktree "):
            cur = relay.norm(line[9:].strip())
        elif line.startswith("locked") and cur == key:
            m = LOCK_PID.search(line)
            return int(m.group(1)) if m else 0
    return None


def terminal_acts(home, s, d, hand):
    """For each terminal worker this session started whose run has ended: the close of its tab and the removal of its
    worktree and branch by git's own commands, after `git worktree unlock`, since a scripted run leaves its lock; or,
    once, the name of one whose work is not landed. One that still runs, or was not started yet, gets no line."""
    out = []
    for t in [t for t in d["terminals"] if not t.get("removed")]:
        name, main = str(t.get("name") or ""), str(t.get("main") or "")
        tree, branch = f"{main}/.claude/worktrees/{name}", f"worktree-{name}"
        if not name or not os.path.isdir(tree):
            if hand and t.get("started"):
                t["removed"] = now()               # it was there and is gone: removed, as the line below asks
            continue
        if hand and not t.get("started"):
            t["started"] = now()
        pid = lock_pid(main, tree)
        if pid and PHI.issues._alive(pid):
            continue                               # its run holds the lock: it still works
        n, got = dirty(tree), on_default(tree, "HEAD")
        if n or n is None or got is not True:
            key = f"terminal:{name}"
            if key not in d["named"]:
                if hand:
                    d["named"] = (d["named"] + [key])[-400:]
                why = (f"holds {n} uncommitted change{'s' * (n != 1)}" if n else "could not be read by git"
                       if n is None else f"holds commits that are not on {default_ref(tree) or 'a default branch'}")
                out.append((f"named:{key}", "named", False,
                            f"left on disk, of the terminal worker `{name}`, whose run has ended: its worktree "
                            f"{tree} {why}. A scripted run takes no message once it has ended, so read its note "
                            f"`report-{name}.md`, land what is whole as the push line says, and name the rest to "
                            f"ezexe once, in one line: a removal by force and a deletion of unmerged work are "
                            f"ezexe's."))
            continue
        how, frm = stand(home, s, main, but=tree)
        rest = ([f"worktree unlock \"{tree}\""] if pid is not None else []) + [f"worktree remove \"{tree}\""]
        if _out(main, "show-ref", "--verify", f"refs/heads/{branch}") is not None and on_default(main, branch) is True:
            rest.append(f"branch -d {branch}")
        if not how:
            continue
        out.append((f"terminal:{name}", "leftover", True,
                    f"leftovers of the terminal worker `{name}`: its run has ended, its worktree is clean and its "
                    f"work is on {default_ref(tree)}. Close its tab with `{CLOSE_TAB}` and `close: true` where "
                    f"`{TABS}` still lists it, then remove them: {cmds_text([git_of(how, frm, r) for r in rest])}. "
                    + ("The unlock is for the lock Claude Code took for the run and left, since a scripted run has "
                       "no exit that releases it. " if pid is not None else "") + LEAVE))
    return out


def route(home, s, text, by, store, back="", d=None, hand=False):
    """Where work that wants a session goes: on a turn a person began, a start; on any other, a message to a live
    worker whose task covers it, else a worker in the Terminal panel, and where `terminal` gives none, the app's
    card with one line to ezexe."""
    cmd = PHI.commands()
    if by == "user":
        return f"start its session with the call `{cmd} draft \"<its words>\"` prints"
    k, ks = fit(home, s["sessionId"], text, store, skip=(back,))
    refused = ("no person began this turn, and the app refuses a new start on such a turn, as the start tool's own "
               "result says, while a message to a live session goes through")
    if k:
        return (f"{refused}: send it by `SendMessage` with `to` `{k}`, to \"{title(k, ks)}\", a live session whose "
                f"task covers it")
    worker = terminal(home, s, text, d, hand)
    # A worker whose worktree is there was started, though terminal_acts, which runs after this, has not marked it
    # yet. Seen in the desktop app: the prompt after a worker's start handed the start lines for it once more.
    if worker and worker[2] and (worker[2].get("started")
                                 or os.path.isdir(f"{worker[1]}/.claude/worktrees/{worker[0]}")):
        return (f"{refused}, and it went to the terminal worker `{worker[0]}` at {worker[2].get('time')}: its "
                f"message and its note `report-{worker[0]}.md` say where it stands")
    if worker:
        return (f"{refused}, and no live session's task covers it: start {TERMINAL} for it, named `{worker[0]}`, "
                f"as the lines after these acts say, which waits on nobody")
    return (f"{refused}, and no live session's task covers it: show it as the app's card, `{START}` with "
            f"`initiation` `own_initiative` and a brief that holds its words, and tell ezexe in one line that the "
            f"card waits. {relay.PUSH[:-1]}")


def item_acts(home, s, d, by, store, hand):
    out = []
    for it in [i for i in d["items"] if not i.get("closed")]:
        k = str(it.get("from") or "")
        ks = relay._session(home, k)
        head = f"item {it['id']}, left by \"{it.get('title') or title(k, ks)}\": \"{it['text']}\""
        ends = (f"It closes on a commit on the default branch that names `{it['id']}`, on `{PHI.commands()} upkeep "
                f"close {it['id']} --note \"<why it is left>\"`, or on ezexe's word.")
        sent = it.get("sent") if isinstance(it.get("sent"), dict) else None
        if sent:
            last = PHI.last_turn_row(home, k) if sent.get("to") == k else {}
            if last and str(last.get("time") or "") > str(sent.get("time") or "") and not working(home, k):
                out.append((f"item:{it['id']}:back", "item", True,
                            f"{head}. It went back to that session at {sent.get('time')}, which reported since, and "
                            f"no commit that names it is on the default branch: read that report, then close it with "
                            f"the note or send it on, where {route(home, s, it['text'], by, store, k, d, hand)}. "
                            f"{ends}"))
            else:
                out.append((f"item:{it['id']}", "item", False,
                            f"{head}. Handed at {sent.get('time')} to go {sent.get('how')}, and still open. {ends}"))
            continue
        if ks.get("sessionId") and live(k, ks) and short_context(home, k, store):
            how = (f"send it back by `SendMessage` with `to` `{k}`: its words, to fix it and land it with "
                   f"`{it['id']}` in the commit message, and to report")
            mark = {"to": k, "how": "back to that session by message", "time": now()}
        else:
            why = "is archived" if not (ks.get("sessionId") and live(k, ks)) else "holds a long context"
            how = f"that session {why}, so it goes to a successor: {route(home, s, it['text'], by, store, k, d, hand)}"
            mark = {"to": "", "how": "to a successor", "time": now()}
        if hand:
            it["sent"] = mark
        out.append((f"item:{it['id']}", "item", True, f"{head}. Still open: {how}. {ends}"))
    return out


def wait_acts(home, s, d, by, store, hand=False):
    out, sid = [], s["sessionId"]
    kids = {k: v for k, v in relay._sessions(home).items() if relay._parent(v) == sid}
    rows = [(f"step {x.get('addr')}, \"{PHI.cut(PHI.clean(x.get('content')), 120)}\"", k, f"step:{x.get('addr')}:{k}",
             str(x.get("content") or ""), "")
            for x, k in plan_waits(home, sid, kids)]
    rows += [(f"{w['id']}, \"{w.get('step')}\"", str(w.get("on") or ""), f"wait:{w['id']}", str(w.get("step") or ""),
              f" Once it is done, close it with `{PHI.commands()} upkeep close {w['id']} --note \"<what was done>\"`.")
             for w in d["waits"] if not w.get("closed")]
    for what, k, key, text, tail in rows:
        ks = kids.get(k) or {}
        if not ks or not (ks.get("archived") or relay.archived_in_app(ks) or finished(home, k, ks)):
            continue
        ok, why, _ = landing(home, k, ks)
        if not ok:
            continue                               # the landing line names it: the step is due once that lands
        out.append((key, "step", True,
                    f"due: {what} waited on \"{title(k, ks)}\" `{k}`, whose work is on its repository's default "
                    f"branch now. Do it in this turn; where it wants a session of its own, "
                    f"{route(home, s, text, by, store, k, d, hand)}.{tail}"))   # never back to the one it waited on
    return out


AGENT_TREE = re.compile(r"^(.*[/\\]\.claude[/\\]worktrees[/\\][^/\\]+)(?:[/\\]|$)")


def agent_trees(home, sid):
    """The git worktrees the subagents of a session wrote in, by the files p4-phi's records hold each one wrote, as
    trees_of gives a tree. One whose agent still runs is left out."""
    seen = {}
    for _, t in plans._tasks(plans.load(home, sid)):
        if not t.get("agent") or t.get("status") == "open":
            continue
        for p in t.get("wrote") or []:
            m = AGENT_TREE.match(str(p))
            if m and relay.norm(m.group(1)) not in seen and os.path.isdir(m.group(1)) and linked(m.group(1)):
                r = _out(m.group(1), "rev-parse", "--abbrev-ref", "HEAD") or ""
                seen[relay.norm(m.group(1))] = {"path": m.group(1), "first": "", "last": "", "there": True,
                                                "own": False, "linked": True, "branch": r}
    return list(seen.values())


# The app keeps the worktree it made for a session that is archived with uncommitted changes, and two of its tools are
# for exactly that. get_storage_usage's own text: it reports the worktrees "kept after archiving because they hold
# uncommitted changes, and for which sessions", and is "Read-only; nothing is asked". discard_kept_worktree's: it
# deletes them, "discarding those changes for good", "The user approves each call on a card ... in every permission
# mode", and "Use it only when the user asked to discard that session's leftover work". So the line names both and
# makes neither call ezexe's standing word.
KEPT = (" Where the app itself kept one of these at the archive, `mcp__ccd_host__get_storage_usage` lists it with its "
        "session and its size, and asks nothing. `mcp__ccd_host__discard_kept_worktree` with that `session_id` "
        "deletes it and its uncommitted changes for good, behind the app's own card in every mode: call it only once "
        "ezexe has said to discard that session's leftover work, and never on `phi.upkeep` alone.")


def leftover_acts(home, s, d, hand):
    """After an archive, and for this session's own subagents: the removal of each clean, merged worktree and branch,
    and, once, the name of each one that is dirty or unmerged."""
    out, sid = [], s["sessionId"]
    groups = [(f"\"{title(k, ks)}\" `{k}`, which is archived", k, trees_of(home, k, ks))
              for k, ks in archived(home, sid).items() if k not in d["swept"]]
    groups.append(("a subagent of this session whose work is merged", "", agent_trees(home, sid)))
    seen = set()
    for whose, k, trees in groups:
        trees = [t for t in trees if relay.norm(t["path"]) not in seen]     # a folder two sessions shared, once
        seen |= {relay.norm(t["path"]) for t in trees}
        cmds, held, waits = removals(home, s, trees, kept=d["mains"])
        if k and hand and not cmds and not waits and not [h for h in held if f"tree:{h[0]}" not in d["named"]]:
            d["swept"][k] = now()                  # nothing of it is left to remove or to name
        if cmds:
            out.append((f"leftover:{k or 'agents'}:{len(cmds)}:{cmds[0][0][-40:]}", "leftover", True,
                        f"leftovers of {whose}: its worktree is clean and its branch merged, so remove them: "
                        f"{cmds_text(cmds)}. {LEAVE}"))
        fresh = [h for h in held if f"tree:{h[0]}" not in d["named"]]
        if fresh:
            if hand:
                d["named"] = (d["named"] + [f"tree:{h[0]}" for h in fresh])[-400:]
            kept = KEPT if k and any("uncommitted change" in w for _, w in fresh) else ""
            out.append((f"named:{k or 'agents'}:{fresh[0][0][-40:]}", "named", False,
                        f"left on disk, of {whose}: " + "; ".join(f"{t}, since {w}" for t, w in fresh)
                        + ". Name each to ezexe once, in one line, and leave it: a removal by force and a deletion "
                          "of unmerged work are ezexe's." + kept))
    return out


# --- the sweep of a session tree: an idle notice from each terminal worker, and one long schedule -------------------
# An orchestrator keeps the sessions it started by a sweep, and what brings it back to one is an event wherever
# Claude Code has one. scheduled-tasks.md opens with "Reacting to events as they happen instead of polling: see
# Channels", and best-practices.md, "Start runs on a schedule or an event", says of a scheduled prompt "Each run is
# another turn in the same session, so don't leave one going in a long conversation". So p4-phi hands no `/loop`.
# Three things bring an orchestrator back, and the first two are events:
# - A session the desktop app started: the app's own note of that session's turn end, which p4-phi adds nothing to.
# - A worker in the Terminal panel, a scripted run on this machine of which the app sends no note: an idle notice.
#   cross-session-messaging.md, "Get a notice when another session goes idle": "Claude can ask one of your sessions
#   on this machine to send back one notice when that session next goes idle or exits", with `SendMessage` and
#   `notify_when_idle`, and "If the asking session is idle, Claude Code starts a new turn with the notice." A
#   session is handed that call once for each worker that runs, and again after each notice while it still runs.
# - What neither tells, a session that stalls with no turn's end and a worker whose notice does not come: one prompt
#   on a long fixed schedule, by `CronCreate` itself and not through the skill `loop`. scheduled-tasks.md, "Manage
#   session-scoped scheduled tasks": "`CronCreate` | Schedule a new task. Accepts a 5-field cron expression, the
#   prompt to run, and whether it recurs or fires once." It is handed once while any worker is out and no schedule
#   is kept, and its end, `CronList` and `CronDelete`, once nothing is live.
# Seen on 2026-11-22, a session of the desktop app on Claude Code 2.1.326 asking scripted `claude -p` runs on 2.1.328:
# - The call answered "Subscribed" for a scripted run, which `ListAgents` listed five seconds after its start, where
#   the same call to another session of the desktop app answers "no idle subscription was made".
# - The notice came for a worker in the asker's own permission mode: queued the instant the worker ended, it began a
#   turn a second after the asker went idle, and it waited while a turn ran there. For a worker in the default mode
#   under an asker that bypasses permission prompts nothing came: by "Control inbound messages" a session that
#   bypasses holds what a session that prompts sends. script_of starts a worker in its starter's own mode.
# - One subscription gave one notice, for the first time the worker was idle, and none at its later turn ends or at
#   its exit. A worker stopped from outside sent none. So the call is handed anew after each notice, and the
#   schedule covers a worker that was stopped.
# The schedule's interval is CRON, the half hour. "How late a recurring task runs": "Unless it runs every five
# minutes, a recurring task starts each run late by up to half the gap to the next run, and by at most 30 minutes",
# so its prompt comes thirty to forty-five minutes apart, inside the hour best-practices.md gives the prompt cache
# on a subscription. It is written off the marks 0 and 30 of the hour, as the tool `CronCreate` asks in its own
# description, "Avoid the :00 and :30 minute marks when the task allows it": "requests from across the planet land
# on the API at the same instant", so "pick a minute that is NOT 0 or 30".
# The sweep's words are SWEEP, kept here and nowhere else, so no orchestrator writes them by hand.
# What a session's own calls did is read at each turn's end, keep_sweep: a `CronCreate` whose prompt holds the
# sweep's opening words begins the schedule, until Claude Code's expiry of a recurring task, and a `CronDelete` of
# its id ends it; a `SendMessage` with `notify_when_idle` asks a worker, until its notice comes as a prompt,
# notice_came, or Claude Code drops the subscription, "If no notice arrives within 12 hours".
# Seen in the desktop app on Claude Code 2.1.326: `CronCreate` with CRON, a prompt and `recurring` true answered
# "Scheduled recurring job 72f3dc05 (7,37 * * * *). Next run: Nov 22 1:44pm.", seven minutes after the mark, where
# a one-shot answers "Scheduled one-shot task efd4cd1b"; `CronList` listed it as its id, its expression, its next
# run and the first eighty characters of its prompt, which hold OPENS whole; and `CronDelete` answered "Cancelled
# job 72f3dc05."
# Nothing is built for a session that still runs a `/loop` an older p4-phi handed it: that loop's own words end it.
CRON_CREATE, CRON_LIST, CRON_DELETE = "CronCreate", "CronList", "CronDelete"
SEND, NOTIFY = "SendMessage", "notify_when_idle"
CRON = "7,37 * * * *"            # when the schedule's prompt comes while a worker is out: each half hour, off 0 and 30
EXPIRY_S = 7 * 86400             # scheduled-tasks.md: "Recurring tasks automatically expire 7 days after creation."
NOTICE_S = 12 * 3600             # cross-session-messaging.md: "If no notice arrives within 12 hours"
NOT_MADE = "no idle subscription"                 # in the call's answer where the app made none
OPENS = "Sweep the sessions this one started, as p4-phi's upkeep has it."
SWEEP = (OPENS + " Read each live session with "
         "`mcp__ccd_session_mgmt__list_sessions` and `linked` true, and each worker in the Terminal panel with `"
         + "mcp__terminal__list_terminal_tabs" + "`. Send on one that stopped with work left, by SendMessage to its "
         "id. Verify one that reports done, on its repository's default branch and on the run of its workflow, "
         "before it counts as done. Do each act p4-phi hands beside this prompt. The app's note of a started "
         "session's turn end and a terminal worker's idle notice are the main wake-ups, so this prompt comes on a "
         "long fixed schedule for what neither tells: a session that stalls with no turn's end, and a worker that "
         "was stopped or whose notice did not come. End the schedule once no session and no terminal worker is "
         "live: read the tasks with `" + CRON_LIST + "` and call `" + CRON_DELETE + "` with the id of the task that "
         "holds these words.")
JOB = re.compile(r"\b(?:job|task)\s+([0-9A-Za-z]{8})\b")  # the id in `CronCreate`'s answer
REF = re.compile(r"\s*\[[0-9a-f]+\]\s*\Z")                # the short identifier `ListAgents` adds to a shared name
# the worker an idle notice names, as the app words the prompt: `[Cross-session idle notice] "<name>", which ...`,
# and the first name in quotes on that line where a notice words it another way, as one of an expired subscription
NOTICE = re.compile(r"\A\s*(?:\[MESSAGE FROM NON-USER SOURCE\b[^\]\n]*\]\s*)?\[Cross-session idle notice\][^\n\"]*"
                    r"\"([^\"\n]+)\"")
NOTICED_MOST = 40                # the workers whose notices are counted, the latest kept


def keep_sweep(s, calls, at=None):
    """Keeps on a session what its own calls of the turn that just ended did for the sweep. `schedule`: the sweep's
    fixed schedule, with `until`, the time Claude Code ends a recurring task by itself, and `id`, the task's own
    where the answer of `CronCreate` gave one; a `CronDelete` ends the schedule kept where it names that id, or
    where none was read. `notices`: each session asked for an idle notice, by the name the call gave, with the time
    Claude Code drops the subscription; a call the app answered with no subscription made keeps none. A turn with
    no such call leaves what is kept. Returns True when either changed."""
    at = time.time() if at is None else at
    before = repr((s.get("schedule"), s.get("notices")))
    for c in calls or []:
        name, inp = c.get("name"), c.get("input") if isinstance(c.get("input"), dict) else {}
        if name == CRON_CREATE:
            if OPENS in str(inp.get("prompt") or "") and inp.get("recurring") is not False:
                made = JOB.search(str(c.get("result") or ""))
                s["schedule"] = {"until": at + EXPIRY_S, "id": made.group(1) if made else ""}
        elif name == CRON_DELETE:
            kept = s.get("schedule") if isinstance(s.get("schedule"), dict) else None
            if kept is not None and (not kept.get("id") or str(inp.get("id") or "") == kept.get("id")):
                s.pop("schedule", None)
        elif name == SEND and inp.get(NOTIFY) is True:
            to = REF.sub("", str(inp.get("to") or "")).strip()
            if to and NOT_MADE not in str(c.get("result") or ""):
                s["notices"] = {**(s.get("notices") if isinstance(s.get("notices"), dict) else {}), to: at + NOTICE_S}
    return repr((s.get("schedule"), s.get("notices"))) != before


def schedule_runs(s, at=None):
    """True while the sweep's fixed schedule is kept as running, by keep_sweep."""
    kept = s.get("schedule") if isinstance(s, dict) else None
    until = kept.get("until") if isinstance(kept, dict) else None
    return isinstance(until, (int, float)) and until > (time.time() if at is None else at)


def asked(s, at=None):
    """The names this session asked for an idle notice that has not come, while Claude Code keeps each subscription."""
    at = time.time() if at is None else at
    kept = s.get("notices") if isinstance(s, dict) and isinstance(s.get("notices"), dict) else {}
    return {k for k, until in kept.items() if isinstance(until, (int, float)) and until > at}


def notice_came(s, prompt):
    """An idle notice that came as a prompt spends the subscription it answers: the session it names is asked no
    more, and the count of notices that came from it rises, which sweep_acts reads to hand the call anew. Returns
    that name, '' for any other prompt."""
    m = NOTICE.match(str(prompt or ""))
    if not m:
        return ""
    name = m.group(1).strip()
    kept = {k: v for k, v in (s.get("notices") if isinstance(s.get("notices"), dict) else {}).items() if k != name}
    if kept:
        s["notices"] = kept
    else:
        s.pop("notices", None)
    came = dict(s.get("noticed") if isinstance(s.get("noticed"), dict) else {})
    came[name] = int(came.pop(name, 0) or 0) + 1       # the latest last
    s["noticed"] = dict(list(came.items())[-NOTICED_MOST:])
    return name


def running(t):
    """True while the run of a terminal worker still works: its worktree is there and git's lock on it names a
    process that lives, as Claude Code writes that lock for the run."""
    name, main = str(t.get("name") or ""), str(t.get("main") or "")
    tree = f"{main}/.claude/worktrees/{name}"
    if not name or not os.path.isdir(tree):
        return False
    pid = lock_pid(main, tree)
    return bool(pid and PHI.issues._alive(pid))


def sweep_acts(home, s, d, hand):
    """What brings this session back to the workers it has out, each line handed once. For each worker in the
    Terminal panel whose run still works and that it has asked for no idle notice: the call that asks, and again
    after each notice while that run still works. While any worker is out and no schedule of the sweep is kept: the
    one `CronCreate` that makes it. And once a schedule runs and nothing is live: its end. A worker is out while it
    is a started session that is not finished, or a worker in the Terminal panel not yet removed. A started session
    is asked for no notice: the app's own note of its turn end tells of it."""
    sid = s["sessionId"]
    live = [k for k, ks in started(home, sid).items() if not finished(home, k, ks)]
    tabs = [t for t in d["terminals"] if not t.get("removed")]
    fixed = schedule_runs(s)
    out = []
    if fixed:
        d.pop("scheduleTold", None)                # a schedule that ends while a worker is out is asked for anew
    else:
        d.pop("scheduleEndTold", None)
    waiting = asked(s)
    came = s.get("noticed") if isinstance(s.get("noticed"), dict) else {}
    told = d.get("noticeTold") if isinstance(d.get("noticeTold"), dict) else {}
    told = {k: v for k, v in told.items() if any(t.get("name") == k for t in tabs)}
    for t in tabs:
        name, n = str(t.get("name") or ""), int(came.get(str(t.get("name") or "")) or 0)
        if not name or name in waiting or told.get(name) == n or not running(t):
            continue
        told[name] = n
        out.append((f"notice:{name}", "sweep", True,
                    f"notice: the terminal worker `{name}` runs, and this session has asked it for no idle notice"
                    + (f" since the last one came" if n else "") + f". Ask it: call `{SEND}` with `to` `{name}`, "
                    f"`{NOTIFY}` true and no `message`, which costs that worker nothing. One `[Cross-session idle "
                    f"notice]` then begins a turn here once it goes idle or exits. It runs in this session's own "
                    f"permission mode, which is what lets its notice through, and one subscription gives one "
                    f"notice. A worker that was stopped from outside sends none, which the sweep's schedule covers."))
    if hand:
        d["noticeTold"] = told
    if (live or tabs) and not fixed and not d.get("scheduleTold"):
        if hand:
            d["scheduleTold"] = now()
        n = len(live) + len(tabs)
        out.append((f"schedule:{sid}", "sweep", any(t.get("started") for t in tabs),
                    f"schedule: this session has {n} worker{'s' * (n != 1)} out and no schedule of the sweep "
                    f"running. Read the tasks with `{CRON_LIST}` first, and where one holds the words below, start "
                    f"none. Otherwise call `{CRON_CREATE}` once, with `cron` `{CRON}`, `recurring` true and, as "
                    f"`prompt`, these words as they stand: \"{SWEEP}\""))
    if not live and not tabs and fixed and not d.get("scheduleEndTold"):
        if hand:
            d["scheduleEndTold"] = now()
        kept = str((s.get("schedule") or {}).get("id") or "")
        out.append((f"schedule-end:{sid}", "sweep", False,
                    f"end the schedule: no session this one started and no worker in the Terminal panel is live, "
                    f"and the sweep's fixed schedule still runs. Read the tasks with `{CRON_LIST}` and call "
                    f"`{CRON_DELETE}` with the id of the task whose prompt opens \"{OPENS}\""
                    + (f", which this session's own `{CRON_CREATE}` call gave as `{kept}`." if kept else ".")))
    return out


def acts(home, s, by="user", store="", hand=False, d=None):
    """Every act due for the sessions `s` started, each as (key, kind, whether it is worth a turn, its line). With
    `hand`, what is handed is marked in `d`, which the caller saves."""
    sid = s["sessionId"]
    d = load(home, sid) if d is None else d
    scan(home, sid, d)
    landed_ids(home, sid, d)
    out = []
    for part in (lambda: archive_acts(home, s, d, hand), lambda: item_acts(home, s, d, by, store, hand),
                 lambda: wait_acts(home, s, d, by, store, hand), lambda: leftover_acts(home, s, d, hand),
                 lambda: terminal_acts(home, s, d, hand), lambda: sweep_acts(home, s, d, hand)):
        try:
            out += part()
        except Exception:  # noqa: BLE001  one act that cannot be read never costs a message the others
            pass
    return out


HEAD_LINE = ("phi (p4-phi): upkeep of the sessions this one started. `phi.upkeep` is on in this project, which is "
             "ezexe's standing word for each act below, so none waits on ezexe: do each in this turn and say in one "
             "line what was done.")
TAIL_LINE = ("A force, a deletion of unmerged work, a credential and a permission setting stay ezexe's.")


def has_tree(home, sid):
    return any(relay._parent(v) == sid for v in relay._sessions(home).values()) \
        or any(t.get("agent") for _, t in plans._tasks(plans.load(home, sid)))


def text(home, s, by="user", store=""):
    """The upkeep lines beside a message, '' with the setting off, for a session that started none, or with nothing
    due. A turn ezexe's own message began gives the module's upkeep wakes their budget again."""
    if not on() or not s.get("sessionId") or not has_tree(home, s["sessionId"]):
        return ""
    sid = s["sessionId"]
    with relay.locked(path(home, sid)):
        d = load(home, sid)
        before = repr(d)
        if by == "user":
            d.pop("woke", None)
        due = acts(home, s, by, store, hand=True, d=d)
        if due:
            d["wokeFor"] = (d["wokeFor"] + [a[0] for a in due if a[0] not in d["wokeFor"]])[-400:]
        if repr(d) != before:
            save(home, sid, d)
    if not due:
        return ""
    said = [f"- {a[3]}" for a in due]
    return "\n".join([HEAD_LINE] + said + [TAIL_LINE] + form(home, s, d, "\n".join(said)))


def wakes(d):
    w = d.get("woke") if isinstance(d, dict) else None
    return int(w.get("n") or 0) if isinstance(w, dict) else 0


def wake(home, sid, store=""):
    """What `phi.py look` answers as `upkeep`, the prompt of a turn the hooks module starts: given when the setting
    is on, the session and every session it started are idle, an act is due that no turn was started for and no
    message carried yet, and the module's wakes are inside `phi.keep_going_max`. '' otherwise."""
    s = relay._session(home, sid)
    if not on() or not s.get("sessionId") or relay.gone(home, s) or working(home, sid) or not has_tree(home, sid):
        return ""
    if any(working(home, k) for k in started(home, sid)):
        return ""
    with relay.locked(path(home, sid)):
        d = load(home, sid)
        if plans.wakes(s) + wakes(d) >= plans.KEEP_GOING_MAX:
            return ""
        before = repr(d)
        due = [a for a in acts(home, s, "event", store, hand=False, d=d) if a[2]]
        new = [a[0] for a in due if a[0] not in d["wokeFor"]]
        if new:
            d["wokeFor"] = (d["wokeFor"] + new)[-400:]
            d["woke"] = {"n": wakes(d) + 1, "time": now()}
        if repr(d) != before:
            save(home, sid, d)
    if not new:
        return ""
    return (f"{MARK} for the sessions this one started: {len(due)} act{'s' * (len(due) != 1)}, each listed beside "
            f"this prompt. p4-phi's hooks module started this turn, since every one of those sessions is idle, and "
            f"ezexe sent no message. Do each act, say in one line what was done, and end the turn.")


def status(home, s, store=""):
    """What `phi.py upkeep` prints: whether the setting is on, the acts due now, and every open item and wait."""
    sid = s["sessionId"]
    lines = [f"phi.upkeep is {'on' if on() else 'off'} for this project"
             + ("" if on() else f": `{PHI.commands()} upkeep on` turns it on")]
    if not on():
        return "\n".join(lines)
    d = load(home, sid)
    due = acts(home, s, s.get("turnBy") or "user", store, hand=False, d=d)
    lines += ["", "Due now:"] + ([f"- {a[3]}" for a in due] or ["- nothing"])
    lines += form(home, s, d, "\n".join(a[3] for a in due))
    timed = [w for w in d["waits"] if w.get("at") and not w.get("closed")]
    if timed:
        lines += ["", "Kept for a scheduled run, which ezexe makes:"]
        lines += [f"- {w['id']}, \"{w.get('step')}\", {w.get('at')}: "
                  + (f"a Desktop scheduled task, by `{DESKTOP_TASK}` on ezexe's yes" if w.get("local")
                     else f"a cloud scheduled task, by `{SCHEDULE}`") for w in timed]
    gave_up = [k for k, n in d["tried"].items() if int(n or 0) >= TRIES]
    if gave_up:
        lines += ["", f"Handed {TRIES} times and left: " + ", ".join(gave_up)]
    done = [i for i in d["items"] + d["waits"] if i.get("closed")]
    if done:
        lines += ["", "Closed:"] + [f"- {i['id']} by {i['closed'].get('how')} at {i['closed'].get('time')}"
                                    for i in done[-20:]]
    return "\n".join(lines)
