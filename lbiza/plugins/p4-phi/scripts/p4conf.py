"""
p4conf.py: p4-phi's reader of `<project>/.claude/p4/p4.json`, its cards set and what it asks p4-temportal's keeper for.

Each plugin carries a p4conf.py of its own, since an installed plugin cannot import another plugin's code: this one
reads the `phi` section of p4.json and p4-temportal's reads the `scratchpad` and `temportal` sections. Each keeps the
other's sections as it finds them. `load(p4)` returns DEFAULTS with the file merged over them. It writes the file when
it is missing, when it lacks a key of DEFAULTS and when a default an older generation of this file wrote has changed,
keeping every value set by hand: WRITTEN records what it wrote. One limit: a value set by hand that equals the value
load recorded as written moves at the next GEN. A file that is not valid JSON is never overwritten: the defaults are
used and a line goes to stderr. Each setting has a variable `P4_<SECTION>_<KEY>`, named by env_name, and `load` reads
one a person set ahead of p4.json for the session's own store; one p4 wrote, or one that does not fit, is passed over
for p4.json's value. p4 writes no such variable: a person's is read ahead of p4.json, and the record's `files` and
`p4past`, which tell p4's own from a person's, are p4-temportal's, read here and never written.

It holds the cards set, CARD_SET, whose id `phi.cards` names and whose yes is kept in the store's phi/cards.json, and
what p4-phi asks the keeper for: want_settings writes the allow rules into the store's settings.local.json, which
p4-temportal's keeper copies into the project's local settings file. The store's layout, where each plugin writes in a
folder of its own, `.claude/p4/<plugin>/`, is p4-temportal's, which moves the files of an earlier layout; `sub(p4,
name, ...)` here is where a kind of file lives, for the two folders p4-phi reads.
"""

import copy
import filecmp
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

FILE = "p4.json"

DEFAULTS = {
    "phi": {                             # p4-phi's session tree
        "home": None,                    # the git remote of a store whose session tree this project shares
        "track": False,                  # true: the session tree in phi/ is committed; false: git ignores it
        "top_orchestrates": True,        # false: an orchestrator works its task list itself, no worker unless asked
        "levels": True,                  # false: no delegation rule
        "plan_mode": True,               # false: p4-phi's plan rule, which hands plan mode, is left out
        "goal_review": True,             # false: a worker's goal asks for no review of its change by a reader
                                         # that has not seen the conversation
        "issues": True,                  # false: the issue loop is off: no open issue a brief names, no commit line
                                         # for it, no regression test at Stop and no push line
        "new_issues": True,              # false: no session is told to publish a new issue, and `gh issue create`
                                         # is asked about in the top session and refused in a started one; an open
                                         # issue a brief names is still taken, with its commit line and push line
        # caps a project sets, ezexe/p4#125, read by phi.CAPS and apply_caps, which keep the default for a value of
        # the wrong type or out of range
        "max_depth": 3,                  # how deep the session tree goes before a session is told to start no more
        "max_children": 8,               # live sessions of one session before it is told to start no more
        "sibling_turns": 5,              # the last turns of the siblings a start background carries
        "own_turns": 3,                  # a session's own last turns its start background carries
        "chain_max": 8,                  # sessions above one whose tasks its background carries
        "turn_steps": 12,                # the steps of one turn a report keeps
        "tree_checks": 6,                # the sessions of the tree checked at once for a stall
        "keep_going_max": 2,             # turns the hooks module starts for upkeep in a row
        "watch_s": 5.0,                  # seconds between two looks of an orchestrator's watcher
        "stale_s": 86400.0,              # seconds a quiet session waits before it counts as stale
        "upkeep": False,                 # true: a session that started others is handed their upkeep as acts that
                                         # wait on nobody; `phi.py upkeep on` and `off` set it
    },
}

# Sections whose keys are ezexe's to choose: merged over the defaults, never called unknown. None of the `phi` section.
OPEN = ()

# Keys read when a project sets them and never written by default, so a later change to the code's own value reaches
# every store: kept as set, never called unknown.
READ_WHEN_SET = ("phi.child_levels", "phi.puppeteer_section", "phi.clear_at", "phi.cards", "phi.worktree_python",
                 "phi.worktree_lines")

# The top-level keys of p4.json that are another plugin's sections: p4-temportal's `scratchpad` and `temportal`, and the
# `claude` and `recall` it reads. _merge keeps them as they are and does not name them as unknown.
OTHERS = ("scratchpad", "temportal", "claude", "recall")

# Where the two kinds of file p4-phi reads live in the store. These are p4-temportal's folders, which it makes and
# moves; p4-phi's own, `phi/`, is named by sub() as it is.
LAYOUT = {
    "memory": "temportal/memory",
    "plans": "temportal/plan-planner",   # the plan files, where plansDirectory points Claude Code, by plan-planner
}


def path(p4):
    return os.path.join(p4, FILE)


def sub(p4, name, *rest):
    """Where `name` lives under `p4`: a key of LAYOUT, or a plugin's own directory such as "phi"."""
    return os.path.join(p4, *LAYOUT.get(name, name).split("/"), *rest)


def _merge(base, over, unknown, prefix=""):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k not in base:
            if prefix + k not in READ_WHEN_SET and (prefix or k not in OTHERS):
                unknown.append(prefix + k)
            out[k] = v                   # kept, so a key a newer plugin copy wrote survives an older copy's rewrite
        elif prefix + k in OPEN and isinstance(base[k], dict) and isinstance(v, dict):
            out[k] = {**base[k], **v}    # keys of ezexe's choosing, such as a cache rule per folder
        elif isinstance(base[k], dict) and isinstance(v, dict):
            out[k] = _merge(base[k], v, unknown, f"{prefix}{k}.")
        else:
            out[k] = v
    return out


def _write(p4, data):
    """Write p4.json through a temp file of this call's own, since the hooks of one event load at once, and with
    the move that waits out a reader, move_over: every hook of every session reads this file."""
    sweep_temps(path(p4))
    fd, tmp = tempfile.mkstemp(prefix=FILE + ".", suffix=".tmp", dir=p4)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        move_over(tmp, path(p4))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# The top-level key of p4.json where load keeps, for each default it wrote, the value and the GEN of the copy that
# wrote it, by the setting's dotted path. A value still equal to its entry was never set by hand. Only a copy with a
# higher GEN moves it to that copy's default, so two installed copies that differ on a default settle on the newer
# one's and never rewrite the file in turn. A value that differs from its entry was set by hand and is never moved.
WRITTEN = "_written"
# The generation of DEFAULTS: raised by one whenever a default changes, so a store's written values follow the
# change. test_p4conf.py pins DEFAULTS to this number. It is raised too when the
# settings keeper gains a key, as at 11 for plansDirectory: an installed copy of a lower GEN then leaves the key to
# the copy that wrote it, where it would otherwise remove it at each of its starts. 12 came with the plans folder's
# move to temportal/plan-planner, so a copy of 11 leaves the new value of plansDirectory and never writes the old one
# back. 13 came with the default `phi.plan_mode`, the switch of p4-phi's plan rule. 14 came with the default
# `phi.goal_review`, the switch of the review a worker's goal asks for.
# 15 came with the default `phi.new_issues` and with the general part of CARD_SET, whose rules an installed copy of
# 14 leaves to the copy that wrote them. 16 came with the removal of the group `recall`, which a store that still
# holds it keeps, since READ_WHEN_SET names it. 17 came with the defaults of p4.json held by the plugin that reads
# them, each in a file of its own. 18 came with the removal of the key `phi.act_dont_wait`, which a store that still
# holds it keeps unread.
GEN = 18


def _leaves(d, prefix=""):
    """(dotted path, value) of every setting of DEFAULTS: a value that is no section, and each key of an OPEN
    section, which ezexe chooses whole."""
    for k, v in d.items():
        p = prefix + k
        if isinstance(v, dict) and v and p not in OPEN:
            yield from _leaves(v, p + ".")
        else:
            yield p, v


def _get(d, dotted):
    for part in dotted.split("."):
        if not isinstance(d, dict) or part not in d:
            return _NONE
        d = d[part]
    return d


def _put(d, dotted, value):
    parts = dotted.split(".")
    for part in parts[:-1]:
        if not isinstance(d.get(part), dict):
            d[part] = {}
        d = d[part]
    d[parts[-1]] = copy.deepcopy(value)


_NONE = object()


def _entry(e):
    """A record entry as (value, gen), or None when it is not one."""
    if isinstance(e, dict) and "v" in e and isinstance(e.get("gen", 0), int):
        return e["v"], e.get("gen", 0)
    return None


def written_record(kept, record):
    """The record load works from: the store's own, or, for a store from before it, every value equal to today's
    default, as written at generation 0."""
    if isinstance(record, dict):
        return record
    out = {}
    for p, v in _leaves(DEFAULTS):
        have = _get(kept, p)
        if have is not _NONE and have == v:
            out[p] = {"v": have, "gen": 0}
    return out


def load(p4, write=True, warn=True, env=True):
    """The merged settings, with each P4_* variable of person_env ahead of p4.json when `env`: one a person set, never
    one the ownership record says p4 wrote, so p4.json stays p4's own source. p4.json never takes a variable's value."""
    merged = _load_file(p4, write, warn)
    if env:
        for key, v in person_env(p4, warn=warn).items():
            _put(merged, key, v)
    return merged


def _load_file(p4, write=True, warn=True):
    """The settings of p4.json merged over DEFAULTS. Writes p4.json when it is missing, lacks a default key or holds a
    default an older generation wrote, if `write` and `p4` exists. Under WRITTEN it records what it wrote and its GEN.
    A section of OPEN, such as temportal.cache, is one setting: when an older copy merges a rule a newer GEN dropped
    back into it, the section no longer equals its entry and counts as set by hand."""
    over, existed = {}, os.path.exists(path(p4))
    if existed:
        try:
            with open(path(p4), encoding="utf-8") as f:
                over = json.load(f)
            if not isinstance(over, dict):
                raise ValueError("not an object")
        except (OSError, ValueError) as e:
            if warn:
                print(f"p4: {path(p4)} unreadable: {e}; defaults used, the file left as it is", file=sys.stderr)
            return copy.deepcopy(DEFAULTS)
    kept = dict(over)
    record = written_record(kept, kept.pop(WRITTEN, None))
    known = dict(_leaves(DEFAULTS))
    now = {p: e for p, e in record.items() if p not in known and _entry(e)}   # another copy's, kept as it wrote it
    for p, default in known.items():
        have, e = _get(kept, p), _entry(record.get(p))
        if have is _NONE:
            now[p] = {"v": default, "gen": GEN}         # missing: written now
        elif e and have == e[0]:
            if e[1] < GEN:
                _put(kept, p, default)                  # an older generation's default: this one's
                now[p] = {"v": default, "gen": GEN}
            else:
                now[p] = record[p]                      # this generation's or a newer one's: left as it is
        # else set by hand: no entry, never moved
    unknown = []
    merged = _merge(DEFAULTS, kept, unknown)
    if warn and unknown:
        print(f"p4: {path(p4)} holds keys this plugin does not read, kept as they are: {', '.join(unknown)}",
              file=sys.stderr)
    out = {**merged, WRITTEN: now}
    if write and os.path.isdir(p4) and (not existed or out != over):
        try:
            _write(p4, out)
        except OSError:
            pass
    return merged


def section(p4, name, write=True):
    return load(p4, write=write)[name]


def set_key(p4, dotted, value):
    """One setting of p4.json set to `value`, as a command of p4's sets it for ezexe: the file is brought up to date
    first, so the key is written beside every default, and a value that differs from the default counts as set by
    hand from then on, which no later load moves."""
    _load_file(p4, write=True, warn=False)
    data = read_json(path(p4)) or {}
    _put(data, dotted, value)
    _write(p4, data)
    return value


def upkeep_on(p4):
    """True when the store turns p4-phi's upkeep of a session tree on, by `phi.upkeep` or its variable."""
    try:
        return _get(load(p4, write=False, warn=False), "phi.upkeep") is True
    except Exception:  # noqa: BLE001 — a store that cannot be read has upkeep off
        return False


# --- p4's settings as P4_* variables ----------------------------------------------------------------------------------
# Every setting of DEFAULTS that steers behaviour, and each phi key of READ_WHEN_SET, has a variable: P4_ and its
# dotted path in upper case with each dot an underscore, such as P4_PHI_MAX_DEPTH for phi.max_depth, apart from the
# names of ENV_NAMES. p4.json stays p4's own source. p4 writes no variable: a person's, in the shell or in a settings
# file, is read ahead of p4.json. Until KEEPER 17 the keeper mirrored each setting a store changed from its default
# under `env` of the project's local settings file, and Claude Code puts that block into the environment of every hook
# of a session, by env-vars.md, but a running session keeps the environment it started with, so a variable an earlier
# keeper wrote can be older than p4.json: load passes over every text the ownership record says p4 wrote, now or
# before, in `files` and `p4past`, and reads a variable ahead of p4.json only when a person set or changed it.
# Decoding, by env_value: empty is unset; for a key that takes a bool, 1, 0, true and false in any case;
# else JSON, and the text itself for a key that takes a string. A value is checked as the key's reader in p4 takes it,
# by ENV_SCHEMA or the default's type, with the items of a list or an object, and anything that does not fit, or fails
# to read at all, is passed over with one stderr line, so the setting falls back to p4.json's value, which is the
# default unless the store changed it. A reader's own range check, such as phi.apply_caps, then keeps the default for a
# value out of range. A section of OPEN, temportal.cache, is merged over its default rules as p4.json's is. A variable
# only ever applies to the store of the session's own project, by env_applies.
ENV_PREFIX = "P4_"
ENV_SKIP = ()                             # the keys of DEFAULTS that are a record and no setting: none
# `phi.cards` has no variable: what is settled with no approval card is in force by the store's file alone, cards_on.
ENV_SET_ONLY = tuple(k for k in READ_WHEN_SET if k.startswith("phi.") and k != "phi.cards")
# A name the rule would give that an older variable of other meaning already has: P4_PHI_WATCH_S is puppeteer.py's
# tick for one run, used whether or not a session is busy, while phi.watch_s is the tick of a busy watcher only.
ENV_NAMES = {"phi.watch_s": "P4_PHI_WATCH_SECONDS"}
# What a key's reader takes where its default does not say: "num" a number, "strs" a list of strings, "levels" plans.child_levels' kinds.
ENV_SCHEMA = {
    "phi.home": str,
    "phi.child_levels": "levels", "phi.puppeteer_section": str,
    "phi.worktree_python": str, "phi.worktree_lines": "strs",
    "phi.clear_at": "num",
}
# The strings a key's reader knows.
ENV_CHOICES = {}
_BAD = object()
_WARNED = set()


def env_name(key):
    return ENV_NAMES.get(key) or ENV_PREFIX + key.upper().replace(".", "_")


def env_keys():
    """{dotted key: its default, or _NONE for a key read only when set}, in the order of DEFAULTS."""
    out = {k: v for k, v in _leaves(DEFAULTS) if k not in ENV_SKIP}
    out.update({k: _NONE for k in ENV_SET_ONLY})
    return out


def _spec(key, default):
    if key in ENV_SCHEMA:
        return ENV_SCHEMA[key]
    if isinstance(default, bool):
        return bool
    if isinstance(default, float):
        return "num"
    if isinstance(default, list):
        return "strs"
    return type(default)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float("inf"),
                                                                                           float("-inf"))


def _fits(key, v, default):
    """True when `v` is what the reader of `key` takes, with its items."""
    if v is None:
        return default is None
    spec = _spec(key, default)
    if spec is bool:
        return isinstance(v, bool)
    if spec is int:
        return isinstance(v, int) and not isinstance(v, bool)
    if spec == "num":
        return _num(v)
    if spec is str:
        return isinstance(v, str) and (key not in ENV_CHOICES or v in ENV_CHOICES[key])
    if spec == "strs":
        return isinstance(v, list) and all(isinstance(x, str) for x in v)
    if spec == "levels":
        return isinstance(v, dict) and all(isinstance(g, dict) and all(isinstance(x, str) for x in g.values())
                                           for g in v.values())
    if spec == "inject":
        return isinstance(v, bool) or v == "rules-facts"
    return False


def env_value(key, text, default=_NONE):
    """The value the variable's `text` gives `key`: _NONE when it is empty, _BAD when it does not fit the key or
    cannot be read."""
    if text is None or text == "":
        return _NONE
    try:
        if _spec(key, default) in (bool, "inject") and text.strip().lower() in ("0", "1", "true", "false"):
            return text.strip().lower() in ("1", "true")
        try:
            v = json.loads(text)
        except ValueError:
            v = text
        if _fits(key, v, default):
            return v
        if _fits(key, text, default):
            return text                                 # a string key's text that reads as JSON of another type
        return _BAD
    except Exception:  # noqa: BLE001 — a variable never breaks a hook, whatever it holds
        return _BAD


def _same_json(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def env_overrides(environ=None, warn=True):
    """{dotted key: value} of every P4_* variable set to a value that fits its key, a section of OPEN merged over its
    default rules as load merges p4.json's."""
    environ = os.environ if environ is None else environ
    out = {}
    for key, default in env_keys().items():
        name = env_name(key)
        v = env_value(key, environ.get(name), default)
        if v is _BAD:
            if warn and (name, environ.get(name)) not in _WARNED:
                _WARNED.add((name, environ.get(name)))
                print(f"p4: {name}={environ.get(name)} does not fit {key}; p4.json's value used", file=sys.stderr)
            continue
        if v is not _NONE:
            out[key] = {**default, **v} if key in OPEN and isinstance(default, dict) else v
    return out


def env_written(p4):
    """{variable: the texts p4 wrote for it}: each one the ownership record says p4 wrote into any local file of
    store `p4`, the entry it owns now and those it replaced or removed, which a running session may still hold. {}
    without a record; None when the record, or any part of it this reads, is malformed, so no variable can be told
    from p4's own."""
    if not os.path.exists(record_path(p4)):
        return {}
    try:
        rec = read_json(record_path(p4))
        if not isinstance(rec, dict):
            return None
        out = {}
        files, past = rec.get("files", {}), rec.get("p4past", {})
        if not isinstance(files, dict) or not isinstance(past, dict):
            return None
        for owned in files.values():
            if not isinstance(owned, dict):
                return None
            for k, e in owned.items():
                if k.startswith(ENV_KEY + "."):
                    if not (isinstance(e, dict) and isinstance(e.get("v"), str)):
                        return None
                    out.setdefault(k.split(".", 1)[1], set()).add(e["v"])
        for texts_of in past.values():
            if not isinstance(texts_of, dict):
                return None
            for name, texts in texts_of.items():
                if not (isinstance(texts, list) and all(isinstance(t, str) for t in texts)):
                    return None
                out.setdefault(name, set()).update(texts)
        return out
    except Exception:  # noqa: BLE001 — a record edited by hand never breaks a load
        return None


def person_env(p4, environ=None, warn=True):
    """env_overrides for store `p4` without a variable whose text p4 wrote, by env_written, and {} for another
    project's store, by env_applies: the variables a person set, which win over p4.json."""
    environ = os.environ if environ is None else environ
    if not env_applies(p4):
        return {}
    got = env_overrides(environ, warn=warn)
    if not got:
        return got
    wrote = env_written(p4)
    if wrote is None:
        return {}                                       # a malformed record: p4.json alone holds
    return {k: v for k, v in got.items() if environ.get(env_name(k)) not in wrote.get(env_name(k), ())}


def env_applies(p4):
    """True when the P4_* variables of this process belong to store `p4`: a session's variables come from its own
    project's settings files, so they apply to that project's store and to no other, such as a shared home store.
    Without CLAUDE_PROJECT_DIR, as in a command run by hand, they apply to any store."""
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project:
        return True
    p4 = os.path.abspath(p4)
    if os.path.basename(p4) != "p4" or os.path.basename(os.path.dirname(p4)) != ".claude":
        return True
    return _norm(main_root(project)[0]) == _norm(os.path.dirname(os.path.dirname(p4)))


# p4-temportal's keeper writes RECORD in the store, kept out of the store's git by the seeded .gitignore. It holds what
# the keeper wrote into which file: the keys under `files` and `p4past` are p4-temportal's, read here by env_written and
# never written.
RECORD = "claude-settings.json"
LOCAL = "settings.local.json"
PLANS = LAYOUT["plans"]          # the store's folder of plan files, from the store's root
ENV_KEY = "env"                  # where an earlier keeper wrote the P4_* variables, each the dotted key env.<name>
# Where the managed settings file sits on each platform, by the managed settings documentation.
MANAGED = {"win": ["C:/Program Files/ClaudeCode/managed-settings.json"],
           "darwin": ["/Library/Application Support/ClaudeCode/managed-settings.json"],
           "linux": ["/etc/claude-code/managed-settings.json"]}


def record_path(p4):
    return os.path.join(p4, RECORD)


# How long a read waits out another process's replace of the file. A file p4 keeps is written whole to a temp file
# and moved over the old one with os.replace, so a reader never meets half a file. On Windows it can meet the move
# itself: open then fails with PermissionError, errno 13, for as long as the move takes. Measured on Windows 11 with
# one process replacing a file in a loop and another reading it: 1250 of 4922 reads failed so, and none with any
# other error. A read taken for "no record" there ran a proof's test a second time and failed a test of the suite
# on GitHub, and one taken for "no JSON object" left p4's settings out of a settings file. The move is over in far
# less than this wait, which is a small part of what a hook has, and relay._write_raw waits out a reader the same
# way from the other side.
READ_WAIT_S = 0.25
READ_AGAIN_S = 0.005


def load_json(p):
    """The JSON value at `p`, as (the value, how the read went): "" where it was read, "missing" where no file is
    there, which is answered at once, and "unreadable" where a file is there and gave no JSON. A read that meets
    PermissionError is made again until READ_WAIT_S has passed, since on Windows that is what a read meets while
    another process's os.replace of the file is under way."""
    end = None
    while True:
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f), ""
        except FileNotFoundError:
            return None, "missing"
        except PermissionError:
            now = time.monotonic()
            end = now + READ_WAIT_S if end is None else end
            if now >= end:
                return None, "unreadable"
            time.sleep(READ_AGAIN_S)
        except (OSError, ValueError):
            return None, "unreadable"


def read_json(p):
    """The JSON object at `p`; {} when it is missing; None when it is there and is not a JSON object. A replace of
    the file by another process is waited out, by load_json."""
    d, how = load_json(p)
    if how == "missing":
        return {}
    return d if isinstance(d, dict) else None


# How long a write waits out a reader, the other side of READ_WAIT_S. On Windows os.replace fails with
# PermissionError, WinError 5, while another process has the file open, as a reader that takes no lock has for the
# length of its read. A move made once lost the write and left its temp. Seen on 2026-11-22: three
# `session.json.<pid>.tmp` beside the records of two sessions, each a whole hook that died at the move by its
# session's log, a prompt hook that handed nothing beside its prompt and two Stop hooks, one of which left its
# turn with no row. Measured on Windows 11 with two processes reading one file in a loop and a third writing it:
# 11455 of 12014 single moves failed. A reader holds the file for one read, so the move is made again every few
# thousandths of a second. The wait is a third of the session lock's, relay.LOCK_WAIT_S, since a save waits
# while it holds that lock, and a small part of what a hook has.
WRITE_WAIT_S = 1.0
WRITE_AGAIN_S = 0.005
# How old a temp of a file is before the next write of that file removes it: one a process that died left, or one
# of a move an older copy gave up on. A live write holds its temp for thousandths of a second.
TEMP_OLD_S = 60.0


def move_over(tmp, p, wait=None):
    """Moves the temp file `tmp` over `p` with os.replace, the one move of the kit's writers. A move that meets
    PermissionError is made again until `wait` seconds have passed, WRITE_WAIT_S where none is given. Then the
    temp is removed and the error raised, so a write that is lost says so and leaves nothing behind."""
    wait = WRITE_WAIT_S if wait is None else wait
    end = None
    while True:
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            now = time.monotonic()
            end = now + wait if end is None else end
            if now >= end:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            time.sleep(WRITE_AGAIN_S)


def sweep_temps(p):
    """Removes each temp of `p` that is older than TEMP_OLD_S, by the names the kit's writers give one: `<p>.tmp`
    and `<p>.<anything>.tmp`. A younger one is another writer's, under way, and is left."""
    old = time.time() - TEMP_OLD_S
    for t in [p + ".tmp"] + glob.glob(glob.escape(p) + ".*.tmp"):
        try:
            if os.path.getmtime(t) < old:
                os.remove(t)
        except OSError:
            pass


def write_whole(p, data, wait=None, sync=False):
    """Writes `data`, text or bytes, to `p` whole or not at all: to a temp file of this writer's own beside it,
    then move_over, which waits out a reader. A temp an earlier write of `p` left is removed first, sweep_temps.
    With `sync` the temp is flushed to the disk before the move. Raises what the write or the move raised, with
    no temp left."""
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    sweep_temps(p)
    tmp = f"{p}.{os.getpid()}.{threading.get_ident()}.tmp"     # one writer's temp file never another's
    try:
        with (open(tmp, "wb") if isinstance(data, bytes) else open(tmp, "w", encoding="utf-8", newline="\n")) as f:
            f.write(data)
            if sync:
                f.flush()
                os.fsync(f.fileno())
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    move_over(tmp, p, wait)


def _norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(p))) if p else ""


def fwd(p):
    return os.path.abspath(p).replace("\\", "/")


def main_root(project):
    """(the main checkout of the git repository holding `project`, True), read from the `.git` files without running
    git: a worktree's `.git` file names its gitdir, whose `commondir` leads to the main `.git`. (project, False)
    outside a repository."""
    d = os.path.abspath(project)
    while True:
        dot = os.path.join(d, ".git")
        if os.path.isdir(dot):
            return d, True
        if os.path.isfile(dot):
            try:
                with open(dot, encoding="utf-8", errors="replace") as f:
                    gitdir = f.read().strip().split("gitdir:", 1)[1].strip()
                gitdir = os.path.normpath(os.path.join(d, gitdir))
                common = os.path.join(gitdir, "commondir")
                if not os.path.isfile(common):
                    return d, True                      # a submodule: its own root
                with open(common, encoding="utf-8", errors="replace") as f:
                    return os.path.dirname(os.path.normpath(os.path.join(gitdir, f.read().strip()))), True
            except (OSError, IndexError):
                return d, True
        up = os.path.dirname(d)
        if up == d:
            return os.path.abspath(project), False
        d = up


def _mine(p):
    uid = getattr(os, "getuid", None)
    if uid is None or not os.path.lexists(p):
        return True
    try:
        return os.lstat(p).st_uid == uid()
    except OSError:
        return True


def settings_file(project, platform=None):
    """The `.claude/settings.local.json` Claude Code reads for a session started in `project`: beside the project's
    own `.claude/settings.json` on Windows, outside a git repository, when the repository root is the home folder or
    when the root, its `.git` or its `.claude` is not the user's; otherwise at the main checkout's root, which a
    worktree session shares. settings.md, "Where Claude Code keeps the local file in a git repository"."""
    platform = platform or sys.platform
    project = os.path.abspath(project)
    root, in_git = main_root(project)
    here = os.path.join(project, ".claude", LOCAL)
    if platform.startswith("win") or not in_git or _norm(root) == _norm(os.path.expanduser("~")):
        return here
    if not all(_mine(os.path.join(root, *p)) for p in ((), (".git",), (".claude",))):
        return here
    return os.path.join(root, ".claude", LOCAL)


def session_project(p4):
    """The folder a session holding store `p4` started in: CLAUDE_PROJECT_DIR when it is in the same repository as
    the store, else the folder that holds the store's `.claude`. None when `p4` is not a `<project>/.claude/p4`."""
    p4 = os.path.abspath(p4)
    if os.path.basename(p4) != "p4" or os.path.basename(os.path.dirname(p4)) != ".claude":
        return None
    home = os.path.dirname(os.path.dirname(p4))
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and os.path.isdir(env) and _norm(main_root(env)[0]) == _norm(home):
        return os.path.abspath(env)
    return home


def _config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def default_memory(project):
    """Claude Code's own auto memory folder for `project`, `<config>/projects/<slug>/memory`, the slug made from the
    main checkout's path as memory.md describes, or CLAUDE_CODE_PROJECT_DIR_NAME where CLAUDE_CONFIG_DIR is set."""
    name = os.environ.get("CLAUDE_CODE_PROJECT_DIR_NAME") if os.environ.get("CLAUDE_CONFIG_DIR") else None
    slug = name or re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(main_root(project)[0]))
    return os.path.join(_config_dir(), "projects", slug, "memory")


# The allow rule ezexe approved for p4 to keep in the local file, so a session runs the p4 commands its hook
# text names without a prompt: phi.py with any arguments. On Windows the same rule in the PowerShell
# form too. Each rule is one entry of `permissions.allow` that
# p4 owns, recorded under RECORD's `rules` with the GEN of the copy that wrote it: p4 adds and removes only its own
# entries, never reorders or drops another, and replaces one when the plugin folder moves, only on a start and only at
# a GEN at least the entry's, so two plugin versions running at once never take each other's entries away. An entry
# deleted by hand is recorded by its identity, the tool form, the script and its arguments without the folder, and
# never written back, wherever the plugin folder moves. Only this file, which sits beside phi.py and so knows the
# path phi.py prints, asks for them, in the store's settings.local.json, which p4-temportal's keeper copies. The
# store's `claude` section sets `allowRules` false to have the keeper remove its entries.
# An installed copy sits in Claude Code's plugin cache at `cache/<marketplace>/<plugin>/<version>/`, and an update
# makes a new version folder beside the old one. plugins/loading.md, "When auto-update runs": "The running session
# keeps the versions it loaded", and "Cleanup of previous versions": Claude Code "removes that directory in a
# background cleanup 14 days later, so a session that already loaded the old version keeps running". So a session
# can run from any version folder still on disk, and the keeper keeps the two rules for each of them beside the
# running copy's, and drops a folder's rules once Claude Code has removed the folder. Each rule names one folder
# exactly: permissions.md, "Wildcard patterns", says "A `*` in a Bash rule matches any text, including spaces", so a
# `*` in place of the version would allow more than this script, and a rule wider than the one ezexe approved is
# ezexe's to write.
ALLOW_KEY = "permissions.allow"
LINE = "@.claude/p4/CLAUDE.md"
PHI_SCRIPTS = None               # the folder of phi.py the rules name; None: this file's own folder, when phi.py is there


def allow_rules(platform):
    """The allow rules for phi.py that p4-phi asks for, or None when this copy has no phi.py beside it and cannot tell
    which. The switch claude.allowRules is the keeper's."""
    here = PHI_SCRIPTS or os.path.dirname(os.path.abspath(__file__))
    if not os.path.isfile(os.path.join(here, "phi.py")):
        return None
    out = []
    for s in [fwd(here)] + version_folders(here):
        cmd = f'python -I -X utf8 "{s}/phi.py" *'
        out.append(f"Bash({cmd})")
        if platform.startswith("win"):
            out.append(f"PowerShell({cmd})")
    return out


_CACHED = re.compile(r"^(.+/cache/[^/]+/[^/]+)/([^/]+)/scripts$")


def version_folders(here):
    """The scripts folders of the other versions of this plugin that Claude Code's plugin cache still holds beside
    the running copy's, each with a phi.py: the folders a session that loaded an older version still runs from. []
    for a copy that is not in the cache's `<plugin>/<version>/` layout, such as a checkout."""
    m = _CACHED.match(fwd(here))
    if not m:
        return []
    try:
        names = sorted(os.listdir(m.group(1)))
    except OSError:
        return []
    return [f"{m.group(1)}/{n}/scripts" for n in names
            if n != m.group(2) and os.path.isfile(os.path.join(m.group(1), n, "scripts", "phi.py"))]


# The ask rules p4 keeps, under RECORD's `askRules`: none. Until KEEPER 15 the keeper wrote one on
# mcp__ccd_session_mgmt__archive_session where `phi.upkeep` was off, in place of p4-phi's own archive guard. An ask
# rule names a tool, never one call, so the app raised its approval card before every archive, 32 times on
# 2026-11-19. ezexe decided that the archive is the last act of a closing ceremony and that a plan moved into
# `complete` is the record ezexe goes back to, so the rule is retired with `phi.upkeep` on or off: with the tuple
# empty _keep_rules takes the entry a copy wrote out of each local file at the store's next whole check, with the
# list p4 made for it, and leaves every ask rule a person wrote. The app's own rule holds, desktop.md, "Work across
# sessions": "You get an approval card before Claude archives a session, except in Auto mode and Bypass permissions
# mode". ASK_RETIRED holds the retired rule's text, which CARD_SET's `archive` and _adopt_ask read.
ASK_KEY = "permissions.ask"
ASK_RETIRED = ("mcp__ccd_session_mgmt__archive_session",)

# --- what is settled before a session's start, with no approval card -------------------------------------------------
# A session another session started stops on no approval card for work its brief covers. desktop.md names the prompt
# an approval card. permissions.md, "Manage permissions": allow rules "let Claude Code use the specified tool without
# manual approval". permission-modes.md, "Actions no mode auto-approves", lists what prompts in every mode, with
# "Tools matched by an explicit ask rule" first, and a question a hook raises is put to a person in every mode too:
# on 2026-11-19 the transcripts of this tree held 39 approvals of p4-phi's own branch guard and 32 of the ask rule
# on the archive tool, every one in a session that bypasses permission prompts.
# What may be settled with no card is a permission, so it is ezexe's to decide. The whole set is CARD_SET, kept here
# and nowhere else, and it is in force for a store only while two things hold: `phi.cards` in that store's p4.json
# holds card_set_id(), the name of the set as this copy has it, and the store's phi/cards.json holds ezexe's yes to
# that set. `phi.py cards on <id>` writes the key and nothing more: the key is what is asked for. The yes is
# kept by cards_yes, which phi.py's hook runs at the end of the shell call that ran the command, and only for a call
# p4-phi's guard had raised its approval card for, so the yes is ezexe's own press, in every permission mode, and
# covers the set whole. No docs page gives a hook a field that says a person approved a call. hooks.md gives
# PostToolUse as fired "after a tool has already executed successfully", and a call the guard answered `ask` for
# runs only once the card is pressed, so that hook's run for that call is the press as p4 can know it. A key
# written any other way, by an edit of p4.json, by set_key, or by the command run where no hook of p4-phi runs,
# such as the app's Terminal panel, has no yes beside it and leaves the set off. The yes is in phi/cards.json, a
# file of p4-phi's own, which the store's seeded .gitignore keeps on one machine, so a yes is no part of a store's
# sync, and it names the store it was given for. Each write replaces the whole file by a rename, so no lock is
# kept. What this does not close: a session runs with ezexe's own rights on the machine, so one that sets out to
# write the file of a press ezexe never made can write that file too.
# A copy whose set differs has another id, so a changed set is in force nowhere until ezexe has said yes to it. The
# key is read from the file alone and has no variable. Nothing in the set lifts a deny rule, and nothing in it
# touches a credential.
CARDS_KEY = "phi.cards"
CARDS_FILE = ("phi", "cards.json")
CARD_TOOLS = ("mcp__p4-phi__note", "mcp__p4-phi__done", "mcp__p4-phi__tree", "mcp__p4-phi__goal",
              "mcp__p4-temportal__lifetime")
# The general part of the set: what a session does in every task. permissions.md: a bare tool name matches every use
# of the tool, and "PowerShell permission rules use the same shape as Bash rules". permission-modes.md:
# "`permissions.allow` rules in settings files do not pre-approve protected-path writes", so no rule here covers a
# settings file under `.claude`, and the default mode approves "File reads inside your working directories" by
# itself, so the part holds no rule for a read: one would add only the reads outside them, where stored logins lie.
# What an argument pattern cannot hold, a force and a deletion, is phi.py's h_force_guard, as permissions.md advises
# a PreToolUse hook where "patterns that try to constrain command arguments are fragile".
GENERAL_RULES = ("Edit", "Write", "Bash(git *)")
GENERAL_WIN = ("PowerShell(git *)",)
CARD_SET = (
    ("tools", "The project's local settings file holds an allow rule for each tool a p4 hooks module declares: "
              + ", ".join(f"`{t}`" for t in CARD_TOOLS) + "."),
    ("archive", "Where `phi.upkeep` is on, an entry of `permissions.ask` in that file that is exactly `"
                + ASK_RETIRED[0] + "` is taken out, also where p4's record no longer holds it as p4's own."),
    ("own-branch", "In a session another session started that works in a git worktree of its own, p4-phi's branch "
                   "guard asks nothing before `git rebase`, `git merge` and `git pull`, which move that worktree's "
                   "own branch and nothing else."),
    ("push", "In such a session p4-phi's branch guard asks nothing before `git push` where the session's brief "
             "tells it to push."),
    ("refusal", "In a session another session started, every other call a guard of p4-phi raises a card for is "
                "refused instead, with the reason and the session to ask by SendMessage: a push its brief does not "
                "tell it to make, a move of a shared checkout to another branch, a hand push or pull of a store, "
                "and a start p4-phi advises another way."),
    ("start", "A session another session started is refused a start whose `permission_mode` is of another class "
              "than its own, since every message between the two would be held, and a start in another folder, "
              "on another host or in the cloud, which the top session makes in a turn of ezexe's."),
    ("general", "The project's local settings file holds an allow rule for each of `Edit`, `Write` and `Bash(git *)`, "
                "and on Windows `PowerShell(git *)`, so a session edits files and runs git with no approval card. No "
                "allow rule lifts Claude Code's own prompt for a write under `.claude`. With the set in force "
                "p4-phi's guard asks ezexe, in every session and every permission mode, before a git command that "
                "forces, that deletes work found nowhere else, or that reads or writes a stored login, and refuses "
                "it in a session another session started."),
)


def card_set_id():
    """The name of CARD_SET as this copy has it: ten hex characters of its hash, which `phi.cards` holds while the
    set is in force."""
    return hashlib.sha256(json.dumps(CARD_SET, ensure_ascii=False).encode("utf-8")).hexdigest()[:10]


def cards_file(p4):
    """The file in store `p4` that holds ezexe's yes to the set, `phi/cards.json`."""
    return os.path.join(p4, *CARDS_FILE)


def _cards(p4):
    """The content of cards_file: {"yes": the yes, "carried": the date}. Where it holds no "carried", the keeper's
    record is read once, and its `cardsYes` taken as the yes where it is an object whose "set" is a text, which is how
    a yes kept before this file stood; "carried" is set to today's date either way and the file is written, where
    the store has a folder."""
    got = read_json(cards_file(p4))
    got = got if isinstance(got, dict) else {}
    if "carried" in got:
        return got
    rec = read_json(record_path(p4))
    yes = rec.get("cardsYes") if isinstance(rec, dict) else None
    if isinstance(yes, dict) and isinstance(yes.get("set"), str):
        got["yes"] = yes
    got["carried"] = time.strftime("%Y-%m-%d")
    if os.path.isdir(p4):
        _write_cards(p4, got)
    return got


def _write_cards(p4, got):
    write_whole(cards_file(p4), json.dumps(got, indent=1, ensure_ascii=False) + "\n")


def cards_on(p4):
    """True when ezexe's yes to the set stands for the store `p4`: `phi.cards` in its p4.json is this copy's
    card_set_id(), and the store's cards.json holds the yes to that set, kept for this store by cards_yes. The two
    files alone are read, so no variable puts the set in force, and neither does a write of the key by itself."""
    try:
        sid = card_set_id()
        if not p4 or cards_asked(p4) != sid:
            return False
        yes = _cards(p4).get("yes")
        return isinstance(yes, dict) and yes.get("set") == sid and _norm(yes.get("store")) == _norm(p4)
    except Exception:  # noqa: BLE001 — a store that cannot be read has the set off
        return False


def cards_asked(p4):
    """The set `phi.cards` names in the store's p4.json, as a text, or '' for none: what was asked for, in force or
    not."""
    try:
        held = _get(_load_file(p4, write=False, warn=False), CARDS_KEY) if p4 else None
    except Exception:  # noqa: BLE001 — a store that cannot be read asks for none
        held = None
    return held if isinstance(held, str) else ""


def cards_yes(p4, **by):
    """Keeps ezexe's yes to the set for the store `p4`, in its cards.json, with what `by` says of the press: the
    session and the call whose approval card ezexe pressed. phi.py's hook after that call is its one caller. The key
    must already name this copy's set, which the approved command wrote, so a card pressed for a command that wrote
    nothing keeps no yes. True when the yes is kept."""
    sid = card_set_id()
    if not p4 or not os.path.isdir(p4) or cards_asked(p4) != sid:
        return False
    got = _cards(p4)
    got["yes"] = {"set": sid, "store": fwd(p4), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                  **{k: str(v) for k, v in by.items() if v}}
    _write_cards(p4, got)
    return True


def cards_no(p4):
    """Takes the kept yes out of the store's cards.json, as the command's `off` does and as its `on` does before it
    writes the key, so each yes is one press for one writing of the key. True when one was there."""
    if not p4 or not os.path.isdir(p4):
        return False
    got = _cards(p4)
    if "yes" not in got:
        return False
    got.pop("yes")
    _write_cards(p4, got)
    return True


# --- what p4-phi asks the keeper for ---------------------------------------------------------------------------------
# p4-phi writes the allow rules it wants into the store's settings.local.json, in Claude Code's settings format, and
# nothing else writes that file. p4-temportal's keeper copies permissions.allow from it into the project's local
# settings file. The key `p4` holds the one thing that format cannot say: `adopt`, the entries of permissions.ask that
# are to be taken out.
ASKS = "settings.local.json"


def asks_file(p4):
    """The file in store `p4` that holds what p4-phi asks the keeper for."""
    return os.path.join(p4, ASKS)


def _same_asks(a, b):
    """Equal as what p4-phi asks for: each list of permissions.allow and p4.adopt without its order."""
    def norm(v):
        v = copy.deepcopy(v) if isinstance(v, dict) else {}
        perms = v.get("permissions")
        if isinstance(perms, dict) and isinstance(perms.get("allow"), list):
            perms["allow"] = sorted(str(x) for x in perms["allow"])
        mine = v.get("p4")
        if isinstance(mine, dict) and isinstance(mine.get("adopt"), list):
            mine["adopt"] = sorted(str(x) for x in mine["adopt"])
        return json.dumps(v, sort_keys=True)
    return norm(a) == norm(b)


def want_settings(p4, platform=None):
    """Writes into the store's settings.local.json what p4-phi asks the keeper for: the allow rules for phi.py of this
    folder and of each cached version folder; with the set in force the tool rules and the general rules too; with
    `phi.upkeep` on as well, p4.adopt. None, and no write, where `p4` is no folder or this copy has no phi.py beside it.
    The file is written only where what it holds differs, each list taken as a set. Returns what is wanted."""
    if not p4 or not os.path.isdir(p4):
        return None
    platform = platform or sys.platform
    rules = allow_rules(platform)
    if rules is None:
        return None
    yes = _cards(p4).get("yes")
    if yes is not None and (not isinstance(yes, dict) or yes.get("set") != cards_asked(p4)):
        cards_no(p4)                                    # the key no longer names the set the yes was for
    on = cards_on(p4)
    allow = list(rules)
    if on:
        allow += list(CARD_TOOLS) + list(GENERAL_RULES) + (list(GENERAL_WIN) if platform.startswith("win") else [])
    want = {"permissions": {"allow": allow}}
    if on and upkeep_on(p4):
        want["p4"] = {"adopt": list(ASK_RETIRED)}
    if not _same_asks(read_json(asks_file(p4)), want):
        write_whole(asks_file(p4), json.dumps(want, indent=2, ensure_ascii=False) + "\n")
    return want


# The marketplace p4's plugins are installed from, which a settings file names in `enabledPlugins`.
MARKET = "p4-marketplace"


