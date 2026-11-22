#!/usr/bin/env python3
"""lifetime.py: p4-temportal's lifetimes, how long a file under `<project>/.claude/p4/temportal/` is kept.

Two kinds of lifetime clear files, as a browser clears its cache and its cookies. A cache rule per folder, in the
p4.json section `temportal.cache` with paths relative to temportal/, clears the files older than `max_age_days`, and
then the oldest files while the folder holds more than `max_mb`. Neither clears a set-aside copy younger than an
hour, which the same start's layout move set aside. The rule of `.layout-conflicts` clears the store's
phi/.layout-conflicts/ too, where a layout move sets aside the older copies of the files in phi/. In both folders a
copy's age starts at the later of its own time and its folder's, since a move keeps the time of the copy it sets
aside and gives the folder it lands in a new one, and neither folder is cleared when it or phi/ is a link or resolves
to any other place. A cookie is one file or folder with its own expiry, set by `lifetime.py set <path> <lifetime>`
and kept in temportal/expires.json. A cache rule whose path resolves to memory/, in any letter case, or to a folder
outside temportal/ clears nothing. A cookie is refused inside memory/, on tmp/ or anything in it, and on the notebook,
src/, plans/ or expires.json themselves: tmp/ holds only the folders an earlier version kept for each session's
scratchpad, and the others are never cleared whole.

plans/ holds the project's plan files, where Claude Code writes them itself once the settings keeper of p4conf.py
has written `plansDirectory`. Claude Code's own cleanup clears a plan in `~/.claude/plans` once it is older than
`cleanupPeriodDays` and does not reach a folder a project names, so the retention sweep clears the plans here at that
same age, by sweep_plans: the days the hooks module read from Claude Code's own merge of the settings and handed
after `--cleanup-days`, the key as the settings files hold it where none is handed, and 30 where no file sets it.
Where the period cannot be told, as with a settings file that cannot be read, no plan is cleared by age, as Claude
Code pauses its own sweep there. A cache rule on `plans` in p4.json stands in place of that age, an empty one keeps
every plan, and a plan file takes a cookie as any other file does. The key holds from the session after the one
whose start wrote it, so `tick` copies the plan files the hooks module names with `--plan` and `--plan-edited` from
Claude Code's own folder into plans/, by keep_plans, and leaves each original.

No lifetime ends with a session. A file that goes when its session goes belongs in that session's scratchpad
directory, which Claude Code makes for the session and deletes with its transcript, by
https://code.claude.com/docs/en/claude-directory.md, "Session scratchpad directory": "Scratchpad files last as long as
the session's transcript". The lifetime `session` cleared a cookie at the SessionEnd of the session that set it, which
a session that is resumed outlives and a session whose process is killed never reaches. `set` refuses it, and a
cookie an earlier version set that way is listed as such and never cleared.

A file the store's git tracks is removed with its removal staged, so its last version stays in the history, and an
ignored or untracked file is deleted. The retention sweep stages those removals and no other change, so an edit
pending elsewhere in the store stays unstaged.

A link under temportal/ is removed as a link: `remove` unlinks it without entering it, so the files it reaches stay.
Each session's scratchpad directory is Claude Code's own, under the system temp directory, and no lifetime here
clears it.

The hooks module, register.ts, runs the retention sweep inside Claude Code: at a session's start, on its timer while
the session runs, and at the session's end.

  tick                     the retention sweep as the module runs it. Before it, as every hook of a start does, it
                           moves files left in an earlier place of the store's layout. It prints one JSON line:
                           `said`, the line of the move when this run made it and the line of what the sweep
                           cleared, `wait_s`, the seconds until the next sweep is due, which is the next
                           cookie's expiry, a minute at least and an hour at most, and `compact_at`, the percent
                           of a session's context at which the module compacts it in a quiet moment, which is the
                           p4.json setting `temportal.compact_at`, 70 where it is unset and 0 for none.
  tick --let-go            starts that sweep in a process of its own and returns at once. The module runs it at a
                           session's end, where the `session.end` hooks share 1.5 seconds and, as the API's types
                           say of SessionEndInput, "only a process a command let go of outlives it".
  set <path> <lifetime>    gives a file or folder under temportal/ a cookie. The path must exist, and a relative
                           one is read from the working folder, and from temportal/ when the working folder holds
                           none there, which is how `list` prints a cookie. The lifetime is `30m`, `12h`, `7d`, `2w`
                           or an ISO date or time.
  list                     every cookie with its expiry, then every cache rule, and the age at which a plan is
                           cleared where no rule names plans/. An entry of expires.json that cannot be read is
                           listed as unreadable, and the retention sweep leaves it as it is.
  clear <path>             removes a cookie and keeps the file, reading a relative path as `set` reads it.
  now                      the retention sweep, run by hand.

The module registers these four as the slash command `/lifetime` and as the tool `lifetime` for the model, and runs
each as this script's command of the same name. Ahead of the command's name it hands `--cleanup-days <value>`, the
setting `cleanupPeriodDays` as Claude Code merged it, where a settings source holds the key.

No command hook runs this script. `sweep` and `session-end`, which the command hooks ran at a session's start and end
before the module did, are gone, and so is the option `--session` of `set`: an installed version runs the scripts of
its own folder in Claude Code's plugin cache, so no session of an older version reaches this file.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402 - the settings file, .claude/p4/p4.json
import hookio  # noqa: E402 - the hook input and link helpers p4-temportal's scripts share

EXPIRES = "expires.json"
NEVER = ("memory",)                     # folders no lifetime ever clears
NOTEBOOK = p4conf.rel("scratchpad").split("/", 1)[-1]    # the notebook's folder under temportal/
PLANS = "plans"                         # the plan files, where plansDirectory points Claude Code
WHOLE = (NOTEBOOK, "src", PLANS, EXPIRES)   # the notebook, saved code, plans and cookies, which no cookie clears whole
# the other plugins' folders of the layout, where a layout move sets copies aside in a .layout-conflicts/ of their own
ASIDE = sorted({place.split("/")[0] for place in p4conf.LAYOUT.values()} - {"temportal"})
UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}
SESSION = "session"                     # the lifetime an earlier version took, and the key of the entries it wrote
NO_SESSION = ("no lifetime ends with a session: a file that goes when its session goes belongs in that session's "
              "scratchpad directory, which Claude Code deletes with its transcript")
FRESH_S = 3600                          # a set-aside copy this young came with this start's move: no rule clears it
NAME = "p4-temportal: "                 # what a line of the sweep starts with, which `now` prints and `tick` leaves off
LEAST_WAIT_S = 60.0                     # the module's timer never sweeps sooner after a sweep than this
MOST_WAIT_S = 3600.0                    # nor later: a cache rule counts days, so an hour is soon enough for one
COMPACT_AT = 70                         # percent of a session's context at which the module compacts it when quiet
CLEANUP_DAYS = 30.0                     # Claude Code's `cleanupPeriodDays` where no settings source holds the key
CLEANUP_KEY = "cleanupPeriodDays"
HANDED_DAYS = "--cleanup-days"          # the option after which the hooks module hands that setting's value


project_root = hookio.project_root


def store_of(root):
    return os.path.join(root, ".claude", "p4")


def home(p4):
    return os.path.join(p4, "temportal")


def rules(p4, warn=True):
    """The cache rules of p4.json, or none when `temportal.cache` is not an object, with a line saying so."""
    r = p4conf.section(p4, "temportal").get("cache", {})
    if isinstance(r, dict):
        return r
    if warn:
        print(f"p4-temportal: temportal.cache in p4.json is not an object, so no cache rule applies: {json.dumps(r)}",
              file=sys.stderr)
    return {}


def parse_lifetime(text, now=None):
    """`30m`, `12h`, `7d`, `2w` or an ISO date or time -> the expiry as epoch seconds. `session` is refused with
    NO_SESSION."""
    now = time.time() if now is None else now
    t = str(text).strip().lower()
    if t == SESSION:
        raise ValueError(f"{NO_SESSION}; use 30m, 12h, 7d, 2w or an ISO date")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([mhdw])", t)
    if m:
        return now + float(m.group(1)) * UNITS[m.group(2)]
    try:
        d = datetime.fromisoformat(str(text).strip())
    except ValueError:
        raise ValueError(f"not a lifetime: {text!r}; use 30m, 12h, 7d, 2w or an ISO date")
    if d.tzinfo is None:
        d = d.astimezone()
    return d.timestamp()


def rel_in(p4, path):
    """`path`, absolute or relative to temportal/, as a path relative to temportal/ with forward slashes once links
    and `..` are resolved, or None when it is temportal/ itself or outside it."""
    h = os.path.realpath(home(p4))
    a = os.path.realpath(path if os.path.isabs(path) else os.path.join(h, path))
    try:
        r = os.path.relpath(a, h)
    except ValueError:
        return None
    if r == "." or r.startswith(".."):
        return None
    return r.replace("\\", "/")


def never(rel):
    return rel.split("/")[0].lower() in NEVER


def read_expires(p4):
    try:
        with open(os.path.join(home(p4), EXPIRES), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_expires(p4, d):
    p = os.path.join(home(p4), EXPIRES)
    if not d:
        try:
            os.remove(p)
        except OSError:
            pass
        return
    # through a temp file of this write's own: the sweeps of two sessions' timers can write at the same moment
    p4conf.replace_text(p, json.dumps(d, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def refusal(p4, path):
    """(rel, None) for a path under temportal/ that may take a cookie, else (rel or None, the reason it may not):
    outside temportal/, inside memory/, on tmp/ or inside it, or one of WHOLE. `set` and the retention sweep both
    ask it, so an entry of expires.json written by hand clears nothing `set` would refuse."""
    rel = rel_in(p4, path)
    if rel is None:
        return None, f"{path} is not under {home(p4)}"
    if never(rel):
        return rel, f"{rel} is in {rel.split('/')[0]}/, which is never cleared"
    if rel.split("/")[0].lower() == "tmp":
        return rel, f"{rel} takes no cookie: tmp/ holds the folders an earlier version kept for each session's scratchpad"
    if rel.lower() in WHOLE:
        return rel, f"{rel} takes no cookie: {NOTEBOOK}/, src/, {PLANS}/ and {EXPIRES} are never cleared whole"
    return rel, None


def set_cookie(p4, path, lifetime, now=None):
    """Give `path`, a file or folder under temportal/, an expiry -> (rel, expiry). A relative `path` is read from
    temportal/, and the command line makes it absolute from the working folder first. Raises ValueError for a path
    outside temportal/, inside memory/, on tmp/ or inside it, that is one of WHOLE or that does not exist, and for a
    lifetime it cannot read."""
    rel, why = refusal(p4, path)
    if why:
        raise ValueError(why)
    if not os.path.lexists(os.path.join(home(p4), *rel.split("/"))):
        raise ValueError(f"{path} does not exist")
    when = parse_lifetime(lifetime, now)
    d = read_expires(p4)
    d[rel] = {"expires": round(when, 3)}
    write_expires(p4, d)
    return rel, d[rel]


def clear_cookie(p4, path):
    rel = rel_in(p4, path)
    d = read_expires(p4)
    if rel in d:
        del d[rel]
        write_expires(p4, d)
        return True
    return False


def named(p4, path):
    """The paths a command's `path` can mean, absolute, the first that holds wins: a relative one is read from the
    working folder and then from temportal/, so `set` and `clear` take a cookie as `list` prints it."""
    here = os.path.abspath(path)
    return [here] if os.path.isabs(path) else [here, os.path.join(home(p4), path)]


def _git(p4, *args):
    try:
        return subprocess.run(["git", "-C", p4, *args], capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None


_own_repo = p4conf._own_repo


def remove(path):
    """Delete a file or a whole folder, removing a link as a link -> the count of files removed."""
    if p4conf.is_link(path):
        try:
            os.unlink(path) if os.path.islink(path) else os.rmdir(path)
            return 1
        except OSError:
            return 0
    if os.path.isdir(path):
        n = sum(len(fs) for _, _, fs in os.walk(path))
        shutil.rmtree(path, ignore_errors=True)
        return n if not os.path.exists(path) else 0
    try:
        os.remove(path)
        return 1
    except OSError:
        return 0


def _files(d, by_folder=False):
    """[(time, size, path)] of every file under `d`, links not followed. The time is the file's modification time, or
    with `by_folder` the later of it and the time of the folder holding the file."""
    out = []
    for base, dirs, names in os.walk(d):
        dirs[:] = [x for x in dirs if not p4conf.is_link(os.path.join(base, x))]
        try:
            since = os.lstat(base).st_mtime if by_folder else float("-inf")
        except OSError:
            continue
        for n in names:
            p = os.path.join(base, n)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            out.append((max(st.st_mtime, since), st.st_size, p))
    return out


def _prune_empty(d, keep):
    for base, dirs, names in os.walk(d, topdown=False):
        if base == keep:
            continue
        try:
            if not os.listdir(base):
                os.rmdir(base)
        except OSError:
            pass


def sweep_cache(p4, now=None, removed=None):
    """Clear by each cache rule in the folder its key resolves to under temportal/, and by the rule of
    .layout-conflicts in the folder of that name that _conflicts_dir finds for temportal/ and for each other plugin,
    where _files reads a copy's age from its folder too -> [(folder from temportal/, files cleared)]. Each file
    removed is added to `removed` when it is a list."""
    now = time.time() if now is None else now
    out = []
    lc = p4conf.LAYOUT_CONFLICTS
    for key, rule in sorted(rules(p4).items()):
        if not isinstance(rule, dict):
            continue
        rel = rel_in(p4, key.strip("/"))
        named = os.path.normpath(key.strip("/")).replace("\\", "/")      # the key as written, no link followed
        if lc in (rel, named):
            places = [(lc, _conflicts_dir(p4, "temportal"), True)]
            places += [(f"../{plugin}/{lc}", _conflicts_dir(p4, plugin), True) for plugin in ASIDE]
        elif rel and not never(rel):
            places = [(rel, os.path.join(home(p4), *rel.split("/")), False)]
        else:
            continue
        for name, d, by_folder in places:
            gone = _clear(d, rule, now, by_folder) if d else []
            if removed is not None:
                removed.extend(gone)
            if gone:
                out.append((name, len(gone)))
    return out


def _conflicts_dir(p4, plugin):
    """The .layout-conflicts/ of `plugin` in the store, or None when that folder is a link, when the folder of a plugin
    other than temportal is one, or when it resolves to any other place, so the rule of .layout-conflicts never clears
    through a link. A temportal/ that is a link is followed, as rel_in follows it for every cache rule."""
    top = os.path.join(p4, plugin)
    d = os.path.join(top, p4conf.LAYOUT_CONFLICTS)
    if p4conf.is_link(d) or plugin != "temportal" and p4conf.is_link(top):
        return None
    real = os.path.realpath(top) if plugin == "temportal" else os.path.join(os.path.realpath(p4), plugin)
    same = os.path.normcase(os.path.realpath(d)) == os.path.normcase(os.path.join(real, p4conf.LAYOUT_CONFLICTS))
    return d if same else None


def _clear(d, rule, now, by_folder=False):
    """Clear the folder `d` by one cache rule -> the paths of the files it removed. With `by_folder` a file's age
    starts at the later of its own time and its folder's, since a layout move keeps the time of the copy it sets
    aside and gives the folder it lands in a new one, and neither `max_age_days` nor `max_mb` clears a copy younger
    than FRESH_S, which the same start's move set aside."""
    if not os.path.isdir(d):
        return []
    files = sorted(_files(d, by_folder))                # oldest first
    gone = []
    age = rule.get("max_age_days")
    if age is not None:
        cutoff = now - float(age) * 86400
        keep = []
        for mt, size, p in files:
            fresh = by_folder and mt > now - FRESH_S     # set aside by this start's layout move
            if mt < cutoff and not fresh and not os.path.basename(p) == ".gitignore" and remove(p):
                gone.append(p)
            else:
                keep.append((mt, size, p))
        files = keep
    cap = rule.get("max_mb")
    if cap is not None:
        total, limit = sum(s for _, s, _ in files), float(cap) * 1024 * 1024
        for mt, size, p in files:
            if total <= limit:
                break
            if by_folder and mt > now - FRESH_S:
                continue                                # set aside by this start's layout move
            if os.path.basename(p) != ".gitignore" and remove(p):
                total -= size
                gone.append(p)
    _prune_empty(d, d)
    return gone


def cleanup_days(root, handed=None):
    """How many days Claude Code keeps what it cleans up by itself -> the days, or None where they cannot be told.
    `handed` is what the hooks module read by `$.settings.read({ key: "cleanupPeriodDays" })`, as JSON: Claude
    Code's own merge of every settings source, what `--settings` carried among them. With none handed, as in a
    command run by hand, the key is read from the settings files of the project at `root`, the managed file over
    the local one over the project's over the user's, and it is CLEANUP_DAYS where no file holds it.

    https://code.claude.com/docs/en/claude-directory.md, "Cleaned up automatically", gives the default as 30 days
    and the least as 1, and says Claude Code pauses its sweep where it "can't safely determine the retention
    period", as with a settings file that "can't be read or parsed". So a file that cannot be read and a value that
    is no number of 1 or more both answer None, and nothing is cleared by an age nobody set."""
    value = None
    if handed is not None:
        try:
            value = json.loads(handed)
        except ValueError:
            return None
    else:
        managed = next((files for name, files in p4conf.MANAGED.items() if sys.platform.startswith(name)), [])
        files = [os.path.join(p4conf._config_dir(), "settings.json"), os.path.join(root, ".claude", "settings.json"),
                 p4conf.settings_file(root), *managed]
        for file in files:                              # rising in precedence: the last file that holds the key
            held = p4conf.read_json(file)
            if held is None:
                return None
            value = held.get(CLEANUP_KEY, value)
    if value is None:
        return CLEANUP_DAYS
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value >= 1:
        return None
    return float(value)


def own_rule(p4):
    """True where temportal.cache holds an entry for plans/, of any shape: the age of the plans is then ezexe's
    word, and an entry with no limit keeps every plan."""
    return any((rel_in(p4, key.strip("/")) or "").lower() == PLANS for key in rules(p4, warn=False))


def sweep_plans(p4, days, now=None, removed=None):
    """Clear the plan files older than `days`, the age at which Claude Code clears a plan in its own folder -> the
    count cleared. None for `days` clears nothing, and so does an entry for plans/ in temportal.cache, which
    sweep_cache then applies in its place. A plans/ that is a link or resolves to another place is left alone, as
    a cache rule's folder is. Each file removed is added to `removed` when it is a list."""
    if days is None or own_rule(p4) or rel_in(p4, PLANS) != PLANS:
        return 0
    gone = _clear(os.path.join(home(p4), PLANS), {"max_age_days": days}, time.time() if now is None else now)
    if removed is not None:
        removed.extend(gone)
    return len(gone)


def _days(days):
    return f"{days:g}"


def sweep_cookies(p4, now=None):
    """Clear every cookie whose time is up -> [rel cleared]. An entry whose expiry cannot be read is left as it is,
    and so is one an earlier version set to end with a session."""
    now = time.time() if now is None else now
    d = read_expires(p4)
    cleared, changed = [], False
    for rel, v in sorted(d.items()):
        try:
            due = isinstance(v, dict) and "expires" in v and float(v["expires"]) <= now
        except (TypeError, ValueError):
            due = False
        if not due or refusal(p4, rel)[1]:
            continue                                    # an entry `set` would refuse is left with its file
        p = os.path.join(home(p4), *rel.split("/"))
        if os.path.lexists(p):
            remove(p)
        if not os.path.lexists(p):
            cleared.append(rel)
            del d[rel]
            changed = True
    if changed:
        write_expires(p4, d)
    return cleared


def _stage_removals(p4, paths):
    """Stage the deletion of each file the store's git tracks that is gone at or under one of `paths`, and nothing
    else, so a pending change to any other file stays unstaged."""
    under = [os.path.relpath(p, p4).replace("\\", "/") for p in paths]
    r = _git(p4, "ls-files", "-z", "--deleted")
    if not (r and r.returncode == 0):
        return
    gone = [f for f in r.stdout.decode("utf-8", "surrogateescape").split("\0")
            if f and any(f == u or f.startswith(u + "/") for u in under)]
    if gone:
        try:
            subprocess.run(["git", "-C", p4, "--literal-pathspecs", "add", "-u", "--pathspec-from-file=-",
                            "--pathspec-file-nul"], input="\0".join(gone).encode("utf-8", "surrogateescape"),
                           capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass


def sweep(p4, now=None, days=None):
    """The retention sweep: the cache rules, then the plans older than `days`, then the cookies, with the removal of
    each tracked file it cleared staged and no other change -> the line to print, or ''. `days` is what
    cleanup_days answered, and None clears no plan by age."""
    if not os.path.isdir(home(p4)):
        return ""
    removed = []
    cache = sweep_cache(p4, now, removed)
    plans = sweep_plans(p4, days, now, removed)
    cookies = sweep_cookies(p4, now)
    if not cache and not plans and not cookies:
        return ""
    if _own_repo(p4):
        _stage_removals(p4, removed + [os.path.join(home(p4), *rel.split("/")) for rel in cookies])
    parts = [f"files past the cache rule: {n}, in {rel}/" for rel, n in cache]
    if plans:
        parts.append(f"plans older than the {_days(days)} days of {CLEANUP_KEY}: {plans}, in {PLANS}/")
    if cookies:
        shown = ", ".join(cookies[:5]) + (f" and {len(cookies) - 5} more" if len(cookies) > 5 else "")
        parts.append(f"expired files: {len(cookies)}, {shown}")
    return NAME + "cleared " + "; ".join(parts) + "."


def start_sweep(p4, days=None):
    """What a start runs: the move of files left in an earlier place of the store's layout, then the retention
    sweep, which clears the plans older than `days` -> the lines to print, the move's first, each starting with
    NAME."""
    moved = p4conf.migrate_layout(p4)
    line = sweep(p4, days=days)
    return ([NAME + "; ".join(moved) + "."] if moved else []) + ([line] if line else [])


def next_wait(p4, now=None):
    """Seconds until the module's timer sweeps again: when the next cookie expires, LEAST_WAIT_S at least and
    MOST_WAIT_S at most. A cookie already past due counts for nothing: the sweep before this either cleared it or
    left it as `set` would refuse it."""
    now = time.time() if now is None else now
    waits = [MOST_WAIT_S]
    for v in read_expires(p4).values():
        try:
            left = float(v["expires"]) - now
        except (TypeError, ValueError, KeyError):
            continue
        if left > 0:
            waits.append(left)
    return max(LEAST_WAIT_S, min(waits))


def compact_at(p4):
    """The percent of a session's context at which the module compacts it in a quiet moment: p4.json
    temportal.compact_at when it is a number above 0 and under 100, 0 when it is 0 or false, which starts no
    compaction, and COMPACT_AT when it is unset or anything else. Claude Code's own compaction stays as it is."""
    at = p4conf.section(p4, "temportal").get("compact_at")
    if at is False:
        return 0
    if not isinstance(at, (int, float)) or isinstance(at, bool):
        return COMPACT_AT
    return at if 0 <= at < 100 else COMPACT_AT


def let_go(args):
    """Start this script with `args` in a process of its own and return at once -> True when it started. The process
    outlives the one that asked and holds none of its handles: on Windows it has a console of its own that shows no
    window, which the git it runs shares, and a process group of its own, and elsewhere a session of its own."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen([sys.executable, "-I", "-X", "utf8", os.path.abspath(__file__), *args],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags if os.name == "nt" else 0, start_new_session=os.name != "nt",
                         close_fds=True)
    except OSError:
        return False
    return True


def own_plans():
    """Claude Code's own folder of plan files. settings-reference.md, `plansDirectory`: unset, "Claude Code uses
    `~/.claude/plans`", which is `plans` in its configuration folder."""
    return os.path.join(p4conf._config_dir(), "plans")


def keep_plans(root, made, edited=()):
    """Copy plan files out of Claude Code's own plans folder into the store's plans/ -> the lines saying so. They
    are there because `plansDirectory` holds from the session after the one whose start wrote it. `made` are the
    files this process's sessions created, and `edited` the ones they wrote again, as the hooks module names them
    at the last sweep.

    The original stays where it is. Seen on Claude Code 2.1.328: a session that was resumed after its plan file had
    been moved still wrote to `~/.claude/plans/<slug>.md`, did not find it, and made it anew, so a move takes a file
    a later process of the same session still uses. Claude Code's own cleanup removes the original with the
    session's transcript.

    Nothing is copied unless the project's local settings file holds the key as the keeper writes it for this store.
    A file is copied only when it is a plain `.md` file directly in Claude Code's own plans folder. One this process
    created is copied where the store holds none of its name, and any of the two kinds is copied over the store's
    file of its name where it is the newer, so a resumed session's edit reaches the copy. A file that was only
    edited and that the store holds no copy of is left alone: another project's session may have made it."""
    p4 = store_of(root)
    target = p4conf.settings_file(root)
    want = p4conf.plans_dir(p4, target)
    have = (p4conf.read_json(target) or {}).get("plansDirectory")
    paths = dict.fromkeys(edited, False) | dict.fromkeys(made, True)
    if not paths or not want or not isinstance(have, str) or not p4conf._same_value("plansDirectory", have, want):
        return []
    own = os.path.normcase(os.path.realpath(own_plans()))
    to = os.path.join(p4, *p4conf.PLANS.split("/"))
    copied = []
    for path, is_made in paths.items():
        name = os.path.basename(path)
        plain = os.path.isfile(path) and not p4conf.is_link(path) and name.lower().endswith(".md")
        if not plain or os.path.normcase(os.path.dirname(os.path.realpath(path))) != own:
            continue
        kept = os.path.join(to, name)
        if os.path.lexists(kept):
            if p4conf.is_link(kept) or not os.path.isfile(kept) or os.path.getmtime(path) <= os.path.getmtime(kept):
                continue                                # the store's file is no older: it stays as it is
        elif not is_made:
            continue
        try:
            os.makedirs(to, exist_ok=True)
            shutil.copy2(path, kept)
        except OSError:
            continue                                    # this plan stays where it is, and the sweep goes on
        copied.append(name)
    if not copied:
        return []
    return [f"copied the plan{'s' if len(copied) > 1 else ''} {', '.join(copied)} from Claude Code's own plans "
            f"folder into {p4conf.PLANS}/, where plansDirectory keeps this project's plans from the next session on."]


CARRIED = (PLANS, NOTEBOOK, "src")      # what a worktree's store keeps for the project: plans, notebook, saved code
OUT = ".out"                            # the notebook's own folder of logs and build output, which is not carried


def carry_over(root):
    """Copy what a session in a git worktree kept for the project into the main checkout's store -> the lines saying
    so. A worktree session's store is `<worktree>/.claude/p4`, since the start hooks take the store from the
    session's root, and a new worktree holds the main checkout's settings file, whose `plansDirectory` is a path
    from the project root. So its plans, its notebook and its saved code lie in the worktree and go when the
    worktree is removed. settings-reference.md, `plansDirectory`: Claude Code stores plans in `~/.claude/plans`
    instead where "the path resolves outside the project root", so the key cannot name the main checkout's folder
    from a worktree, and the files are carried instead.

    Every sweep carries, the one at a session's start, the timer's and the last one, so a session that is killed has
    lost at most what it wrote since the sweep before. A file is copied where the main checkout's store holds none
    of its name or an older one, and nothing is ever removed on either side. Links, the notebook's `.out` and a
    folder's own git are left where they are. Nothing is carried where the main checkout has no store."""
    main, in_git = p4conf.main_root(root)
    if not in_git or os.path.normcase(os.path.realpath(main)) == os.path.normcase(os.path.realpath(root)):
        return []
    here, there = os.path.join(store_of(root), "temportal"), os.path.join(store_of(main), "temportal")
    if not os.path.isdir(store_of(main)) or p4conf.is_link(here) or not os.path.isdir(here):
        return []
    carried = 0
    for name in CARRIED:
        top = os.path.join(here, name)
        if p4conf.is_link(top) or not os.path.isdir(top):
            continue
        for folder, dirs, files in os.walk(top):
            dirs[:] = [d for d in dirs if d not in (OUT, ".git") and not p4conf.is_link(os.path.join(folder, d))]
            for file in files:
                path = os.path.join(folder, file)
                kept = os.path.join(there, os.path.relpath(path, here))
                try:
                    if p4conf.is_link(path) or not os.path.isfile(path) or p4conf.is_link(kept):
                        continue
                    if os.path.lexists(kept) and (not os.path.isfile(kept)
                                                  or os.path.getmtime(path) <= os.path.getmtime(kept)):
                        continue                        # the main checkout's file is no older: it stays as it is
                    os.makedirs(os.path.dirname(kept), exist_ok=True)
                    shutil.copy2(path, kept)
                except OSError:
                    continue                            # this file stays in the worktree, and the sweep goes on
                carried += 1
    if not carried:
        return []
    return [f"carried {carried} file{'s' if carried > 1 else ''} of this worktree's plans, notebook and saved code "
            "into the main checkout's store, where they stay when the worktree is removed."]


def tick(root, to_let_go=False, made=(), edited=(), handed=None):
    """The module's sweep for the project at `root` -> what it prints as one JSON line. With `to_let_go` the sweep
    runs in a process let go of, and here only when none could be started. `made` and `edited` are the plan files
    the process's sessions created and wrote again in a folder named `plans`, which keep_plans copies into the store
    before the sweep, in the process that sweeps. `handed` is what the module handed after HANDED_DAYS, which
    cleanup_days reads and the process let go of is handed too. A failure is said, never raised."""
    named = [word for path in made for word in ("--plan", path)]
    named += [word for path in edited for word in ("--plan-edited", path)]
    if to_let_go and let_go([*([] if handed is None else [HANDED_DAYS, handed]), "tick", *named]):
        return {"let_go": True}
    p4 = store_of(root)
    try:
        said = keep_plans(root, made, edited)
        said += carry_over(root)
        days = cleanup_days(root, handed)
        said += [line[len(NAME):] if line.startswith(NAME) else line for line in start_sweep(p4, days)]
        return {"said": said, "wait_s": round(next_wait(p4), 3), "compact_at": compact_at(p4)}
    except Exception as e:  # noqa: BLE001 — a sweep degrades, never raises
        return {"said": [f"the retention sweep degraded: {type(e).__name__}: {e}"], "wait_s": MOST_WAIT_S}


def listing(p4, now=None, days=None, is_told=False):
    """Every cookie, then every cache rule, then the age at which a plan is cleared where no rule names plans/.
    `days` is what cleanup_days answered, and with `is_told` a None of it is listed as an age that cannot be told."""
    now = time.time() if now is None else now
    lines = []
    for rel, v in sorted(read_expires(p4).items()):
        line = ""
        try:
            if "expires" in v:
                t = float(v["expires"])
                when = datetime.fromtimestamp(t, timezone.utc).astimezone().isoformat(timespec="minutes")
                line = f"cookie  {rel}  expires {when}" + ("  past due" if t <= now else "")
            elif SESSION in v:
                line = (f"cookie  {rel}  set by an earlier version to end with session {str(v[SESSION])[:8]}, so "
                        "never cleared: set a lifetime on it or clear it")
        except (TypeError, ValueError, OverflowError, OSError):
            pass
        why = refusal(p4, rel)[1]
        if why:
            line = f"cookie  {rel}  refused, so never cleared: {why}"
        lines.append(line or f"cookie  {rel}  unreadable, so never cleared: {json.dumps(v)}")
    raw = p4conf.section(p4, "temportal").get("cache", {})
    if not isinstance(raw, dict):
        lines.append(f"cache   temportal.cache is not an object, so no cache rule applies: {json.dumps(raw)}")
    for rel, rule in sorted(rules(p4, warn=False).items()):
        lines.append(f"cache   {rel}/  " + (", ".join(f"{k}={v}" for k, v in rule.items()) if isinstance(rule, dict)
                     else f"not an object, so never applied: {json.dumps(rule)}"))
    if not own_rule(p4) and days is not None:
        lines.append(f"cache   {PLANS}/  max_age_days={_days(days)}, the {CLEANUP_KEY} at which Claude Code clears "
                     "a plan in its own folder, since no cache rule names plans/")
    elif not own_rule(p4) and is_told:
        lines.append(f"cache   {PLANS}/  no plan is cleared by age: {CLEANUP_KEY} cannot be told from the settings")
    return lines


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    handed = None
    if args[:1] == [HANDED_DAYS] and len(args) > 1:     # the module's, ahead of the command's name
        handed, args = args[1], args[2:]
    sub = args[0] if args else ""
    if sub == "tick":                   # the module's: it reads no stdin, and the project is CLAUDE_PROJECT_DIR
        made = [args[i + 1] for i, word in enumerate(args[:-1]) if word == "--plan"]
        edited = [args[i + 1] for i, word in enumerate(args[:-1]) if word == "--plan-edited"]
        print(json.dumps(tick(project_root({}), "--let-go" in args[1:], made, edited, handed), ensure_ascii=False))
        return 0
    import argparse
    ap = argparse.ArgumentParser(prog="lifetime.py", description="p4-temportal: cookie and cache lifetimes")
    ap.add_argument("--p4", default=None, help="the store, <project>/.claude/p4, by default from CLAUDE_PROJECT_DIR")
    ap.add_argument(HANDED_DAYS, dest="handed", default=handed,
                    help="cleanupPeriodDays as Claude Code merged it, as JSON, by default read from the settings files")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("set", help="give a file or folder under temportal/ an expiry")
    s.add_argument("path")
    s.add_argument("lifetime", help="30m, 12h, 7d, 2w or an ISO date")
    c = sp.add_parser("clear", help="remove a file's expiry, keeping the file")
    c.add_argument("path")
    sp.add_parser("list", help="every cookie and cache rule")
    sp.add_parser("now", help="run the retention sweep now")
    a = ap.parse_args(args)
    p4 = a.p4 or store_of(project_root({}))
    days = cleanup_days(p4conf.session_project(p4) or project_root({}), a.handed)
    if a.cmd == "set":
        places = named(p4, a.path)
        try:
            rel, v = set_cookie(p4, next((p for p in places if os.path.lexists(p)), places[0]), a.lifetime)
        except ValueError as e:
            print(f"lifetime.py: {e}", file=sys.stderr)
            return 2
        print(f"{rel}: expires " + datetime.fromtimestamp(v["expires"]).isoformat(timespec="minutes"))
    elif a.cmd == "clear":
        print("cleared" if any(clear_cookie(p4, p) for p in named(p4, a.path)) else "no expiry was set")
    elif a.cmd == "list":
        print("\n".join(listing(p4, days=days, is_told=True)) or "nothing has a lifetime")
    else:
        print(sweep(p4, days=days) or "nothing has expired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
