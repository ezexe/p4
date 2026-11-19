"""
p4conf.py: the settings of every p4 plugin, kept in one file of the store, `<project>/.claude/p4/p4.json`.

Each plugin carries its own copy of this file, since an installed plugin cannot import another plugin's code, and
test_p4conf.py holds the copies the same byte for byte. `load(p4)` returns DEFAULTS with the file merged over them. It
writes the file when it is missing, when it lacks a key of DEFAULTS and when a default an older generation of this
file wrote has changed, keeping every value set by hand: WRITTEN records what it wrote. Two limits: a value set by
hand that equals the value load recorded as written moves at the next GEN, and in a store from before the record a
value set by hand that equals a past default in HISTORY moves. A file that is not valid JSON is never overwritten: the
defaults are used and a line goes to stderr. Each setting has a variable `P4_<SECTION>_<KEY>`, named by env_name,
and `load` reads one a person set ahead of p4.json for the session's own store; one p4 wrote, or one that does not
fit, is passed over for p4.json's value. The settings keeper below mirrors each setting a store changed from its
default as such a variable under `env` of the project's local settings file, and reads CLAUDE_PROJECT_DIR and
CLAUDE_CONFIG_DIR, as Claude Code sets them.

It also holds the store's layout: each plugin writes in a folder of its own, `.claude/p4/<plugin>/`, beside p4.json
and the store's own git files. `sub(p4, name, ...)` is where a kind of file lives and `rel(name, ...)` the same path
as git names it. `migrate_layout(p4)` moves files from an earlier place of the layout into their plugin's folder.
Every plugin calls it at its start, so whichever plugin runs first moves them.

It also keeps the Claude Code settings p4 relies on, ezexe/p4#246: `keep_settings(project)` writes
`autoMemoryDirectory`, `attribution.commit` when the store gives a text, and the `P4_*` variables that mirror the
settings p4.json changes under `env` into the project's `.claude/settings.local.json`, merged with what is there,
and records what it owns in the store's RECORD.
"""

import copy
import filecmp
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time

FILE = "p4.json"

DEFAULTS = {
    "scratchpad": {
        "asks": False,                   # repo-uses, the start line on code the repo uses; P4_SCRATCHPAD_ASKS wins
        "tmp": False,                    # no link from a session's scratchpad to temportal/tmp: p4-temportal 0.3.9
                                         # and older read it and link when it is missing or true, so it is kept false
        # the extensions and folder names the notebook moves into its .out/
        "ignorable_ext": ["log", "out", "tmp", "dump", "pid", "o", "obj", "pdb", "ilk", "exe", "dll", "lib", "so",
                          "dylib", "a", "class", "pyc", "pyo", "tlog", "binlog", "etl", "trace", "lastbuildstate"],
        "ignorable_dirs": ["bin", "build", "obj", "logs", "out", "dist", "target", "node_modules", "__pycache__",
                           ".cache", "cmake-build-debug", "cmake-build-release", "x64", "debug", "release"],
        "repo_uses_min_name": 6,         # a basename shorter than this matches too much to call it a use
        "repo_uses_max": 200,            # candidate names one git grep carries
        "repo_uses_lines": 10,           # lines printed at most; the rest counted on one more
    },
    "phi": {                             # p4-phi's session tree
        "home": None,                    # the git remote of a store whose session tree this project shares
        "track": False,                  # true: the session tree in phi/ is committed; false: git ignores it
        "act_dont_wait": True,           # false: p4-phi's act-don't-wait rule is left out in this project
        "top_orchestrates": True,        # false: an orchestrator works its task list itself, no worker unless asked
        "levels": True,                  # false: no delegation rule
        "issues": True,                  # false: the issue loop is off: no open issue a brief names, no commit line
                                         # for it, no regression test at Stop and no push line
        # caps a project sets, ezexe/p4#125, read by phi.CAPS and apply_caps, which keep the default for a value of
        # the wrong type or out of range
        "max_depth": 3,                  # how deep the session tree goes before a session is told to start no more
        "max_children": 8,               # live sessions of one session before it is told to start no more
        "sibling_turns": 5,              # the last turns of the siblings a start background carries
        "own_turns": 3,                  # a session's own last turns its start background carries
        "chain_max": 8,                  # sessions above one whose tasks its background carries
        "turn_steps": 12,                # the steps of one turn a report keeps
        "tree_checks": 6,                # the sessions of the tree checked at once for a stall
        "keep_going_max": 2,             # times the Stop hook sends a turn with open steps back
        "watch_s": 5.0,                  # seconds between two looks of an orchestrator's watcher
        "stale_s": 86400.0,              # seconds a quiet session waits before it counts as stale
    },
    "temportal": {                       # lifetimes under .claude/p4/temportal/, read by p4-temportal's lifetime.py
        "cache": {                       # a rule per folder, relative to temportal/, and memory/ is never cleared
            "notebook/.out": {"max_age_days": 14, "max_mb": 500},     # the logs, build output and binaries moved here
            ".layout-conflicts": {"max_age_days": 30},                 # the older copies a layout move set aside
        },
    },
    "recall": {                          # p4-phi's retrieval
        "inject": "rules-facts",         # what reaches the model: false none, "rules-facts" only rule and fact lines,
                                         # true every line; P4_RECALL_INJECT=0, 1 or rules-facts wins for a run
        "learn": True,                   # false: the Stop hook trains nothing, and labels are still written
        "updated": None,                 # who last set inject and learn, and when: ezexe/phi's phi_model mode writes it
        "repo_deadline_s": 8.0,
        "deps": {                        # frameworks, library packages and external modules as entries, by deps.py
            "auto": True,                # node_modules, vendor, third_party, _deps, vcpkg_installed, site-packages
            "roots": [],                 # more roots: paths relative to the project, or absolute paths outside it
            "deadline_s": 6.0,           # what one hook spends reading changed packages; the rest waits for the next
            "max_entries": 20000,
            "package_files": 3,          # files read of one package beyond those a session opened, and entries
            "package_entries": 40,       # kept of it: more of either measured worse on silence and precision
            "scan": 20000,               # directory entries one package's walk looks at
            "depth": 6,
        },
        "said": {                        # what a session states about the lines it was shown, by said.py
            "mode": "off",               # "off", "shadow" to ask and write it down, or "on" for training to read it
        },
        "lookups": {                     # each tool call recorded and checked before the next like it, by lookups.py
            "on": True,
            "web": "note",               # what an earlier finding for the same question does: "note" beside the
            "shell": "shadow",           # call, which runs, "answer" in place of the call, once, "shadow" logged
                                         # only, or "off"
            "after": True,               # a failure other sessions met is told what they did about it
            "threshold": None,           # None: the trained threshold, and 0.6 before a first round
            "min_precision": 0.85,       # how often an answered call must be right for a threshold to be taken
            "max_age_days": 30,          # an older finding is not handed back
            "finding_chars": 4000,       # kept of a web call's answer
            "shown_chars": 1500,         # shown of it
            "epochs_web": 30,            # training rounds of the web model and passes of the failure model, as the
            "epochs_shell": 6,           # held-out runs noted in lookups.py chose them
        },
        "near": {                        # candidates from what earlier, similar tasks used, by near.py
            "on": True,
            "neighbours": 20,            # earlier tasks whose entries are taken
            "max": 100,                  # entries added to a task's candidates
            "same_session": False,       # the session's own earlier tasks too: scores well, tells it nothing
        },
        "node": {                        # the session tree, by node.py
            "on": False,                 # true: entries the sessions above used are candidates and a training feature
        },
        "sync": {                        # every machine's branch of the store kept in step, by sync.py
            "seed": True,                # the layout hook writes .github/workflows/p4-sync.yml and .github/p4_sync.py
            "main": "main",              # the branch the machines' branches are merged into
        },
        "query": {
            "max_lines": 5, "per_file": 2, "text_chars": 160, "history_chars": 120, "candidates": 200,
            "min_rare": 2, "fallback_cover": 0.75, "fallback_icover": 0.65, "fallback_dense": 0.35,
            "file_shared": 4, "file_cover": 0.55, "file_dense": 0.75,
            "variant_weight": 0.5, "expand_weight": 0.5,
        },
        "train": {
            "candidates": 200, "train_neg": 60, "folds": 5, "floor_drop": 0.02, "min_precision": 0.6,
            "first_floor": 0.36, "owed_labels": 10, "owed_age_s": 3600, "max_tasks": 400,
        },
        "teacher": {
            "model": "claude-fable-5-2", "second_opinion": "claude-opus-5-5", "cutoff": None, "effort": "high",
            "max_tokens": 16000, "agree_min": 0.65, "newer_max": 12, "cand_k": 60, "dict_batch": 20,
        },
    },
}

# Sections whose keys are ezexe's to choose: merged over the defaults, never called unknown.
OPEN = ("temportal.cache",)

# Keys read when a project sets them and never written by default, so a later change to the code's own value reaches
# every store: kept as set, never called unknown.
READ_WHEN_SET = ("phi.child_levels", "phi.puppeteer_section", "phi.clear_at", "claude")

# Keys no plugin reads, top-level or dotted: never returned or called unknown, and dropped from p4.json when it is
# rewritten for another reason. The memory section and the scratchpad tmp keys went with p4-temportal's move to the
# app's own auto memory and scratchpad, and phi.session_archives with the archive guard, which the app's approval card
# on the archive tool replaced. phi.puppeteer_chars and phi.compactions steer nothing: Claude Code compacts a session
# by itself, so a puppeteer's boundary notice carries no compact question to count characters or compactions for.
# phi.context_window steers nothing either: the app counts a session's context, and a session reads its share with
# the app's get_usage tool, so p4 holds no window size to count against. phi.file_sets went with the refusal of a
# start whose brief declares no files: a session that writes works in a git worktree of its own, so no start is
# held or refused for the files its brief names. recall.pinned_chars went with the pinned rules block of a start:
# Claude Code loads the rules files under `.claude/rules/` itself, at launch and after a compaction.
RETIRED = ("plans", "version", "memory", "scratchpad.tmp_idle_days", "scratchpad.tmp_max_file_mb",
           "scratchpad.tmp_max_files", "scratchpad.tmp_empty_idle_hours", "scratchpad.scratch_sweep_minutes",
           "scratchpad.tmp_skip_dirs", "phi.session_archives", "phi.puppeteer_chars", "phi.compactions",
           "phi.context_window", "phi.file_sets", "recall.pinned_chars")

# Where each kind of file lives in the store, by plugin. p4-temportal keeps the auto memory, the notebook and saved
# code in temportal/, and p4-phi keeps its session tree, the retrieval corpus and
# models, and the archive a migration from the per-session layout keeps verbatim in phi/. p4.json and the store's own
# git files stay at the top: .git, .github, .gitignore and .gitattributes.
LAYOUT = {
    "memory": "temportal/memory",
    "scratchpad": "temportal/notebook",
    "src": "temportal/src",
    "store": "phi/store",
    "models": "phi/models",
    "archive": "phi/archive",      # what migrate.py keeps verbatim from a per-session tree, and its report
}
# Each kind's earlier places in a store, oldest first: at the top of the store, and under recall/ for the corpus
# and the models. migrate_layout moves files from any of them.
OLDER = {k: [k] for k in LAYOUT}
OLDER["store"].append("recall/store")
OLDER["models"].append("recall/models")
OLDER["scratchpad"].append("temportal/scratchpad")     # the notebook, before the session scratchpad left the store
LAYOUT_LOCK = ".layout.lock"              # held while one hook moves the store; the others wait for it
LAYOUT_CONFLICTS = ".layout-conflicts"    # inside the plugin's folder: the older of two differing copies


def path(p4):
    return os.path.join(p4, FILE)


def sub(p4, name, *rest):
    """Where `name` lives under `p4`: a key of LAYOUT, or a plugin's own directory such as "phi"."""
    return os.path.join(p4, *LAYOUT.get(name, name).split("/"), *rest)


def rel(name, *rest):
    """sub() relative to the store, with forward slashes: the path git and .gitignore use."""
    return "/".join([LAYOUT.get(name, name), *rest])


def is_link(p):
    """A symlink or a Windows junction."""
    if os.path.islink(p):
        return True
    isj = getattr(os.path, "isjunction", None)        # 3.12+
    if isj:
        return isj(p)
    try:
        return bool(os.lstat(p).st_file_attributes & 0x400)   # FILE_ATTRIBUTE_REPARSE_POINT
    except (OSError, AttributeError):
        return False


def _same(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _make_link(link, target):
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(os.path.abspath(target), os.path.abspath(link))
    else:
        os.symlink(os.path.abspath(target), link, target_is_directory=True)


def _unlink(link):
    if os.path.islink(link):
        os.unlink(link)
    else:
        os.rmdir(link)                                  # a junction: RemoveDirectory drops the reparse point only


# The files a move put in a new place in this process, so the layout commit holds those and nothing else.
_LANDED = []
_STORE = []                                       # the store being moved, for _ignored


def _ignored(path):
    """True when the store's git ignores `path`, as it ignores a cache, which is never set aside."""
    if not _STORE:
        return False
    try:
        r = subprocess.run(["git", "-C", _STORE[0], "check-ignore", "-q", "--no-index", path], capture_output=True,
                           timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _merge_tree(src, dst, aside):
    """Move every file of `src` into `dst`. A file `dst` lacks is moved in and an identical one dropped. Of two that
    differ the newer is kept in `dst` and the older goes to `aside` under the same relative path. Returns the count
    kept aside. A file that cannot move, held open or moved by another hook, is left for the next start."""
    aside_n = 0
    for d, dirs, names in os.walk(src, topdown=False):
        for n in names:
            s = os.path.join(d, n)
            r = os.path.relpath(s, src)
            t = os.path.join(dst, r)
            try:
                if not os.path.lexists(t):
                    os.makedirs(os.path.dirname(t), exist_ok=True)
                    _note(s, t)
                    os.replace(s, t)
                    _LANDED.append(t)
                elif os.path.isfile(t) and filecmp.cmp(s, t, shallow=False):
                    _note(s, None)
                    os.remove(s)
                elif _ignored(t):
                    # a file git ignores: the newer stays and the older is set aside as a tracked one is, but left out
                    # of the layout commit, which holds no ignored file
                    old = t if os.path.getmtime(s) > os.path.getmtime(t) else s
                    a = os.path.join(aside, r)
                    os.makedirs(os.path.dirname(a), exist_ok=True)
                    if os.path.lexists(a):
                        a += time.strftime(".%Y%m%d-%H%M%S")
                    if old is s:
                        _note(s, None)                  # gone from its earlier place, as the commit sees it
                    os.replace(old, a)
                    _LANDED.append(a)
                    if old is t:
                        _note(s, t)
                        os.replace(s, t)
                    aside_n += 1
                else:
                    old = t if os.path.getmtime(s) > os.path.getmtime(t) else s
                    a = os.path.join(aside, r)
                    os.makedirs(os.path.dirname(a), exist_ok=True)
                    if os.path.lexists(a):
                        a += time.strftime(".%Y%m%d-%H%M%S")
                    _note(old, a)
                    os.replace(old, a)
                    _LANDED.append(a)
                    if old is t:
                        _note(s, t)
                        os.replace(s, t)
                        _LANDED.append(t)
                    aside_n += 1
            except OSError:
                continue
        for n in dirs:
            p = os.path.join(d, n)
            if not is_link(p):
                try:
                    os.rmdir(p)
                except OSError:
                    pass
    try:
        os.rmdir(src)
    except OSError:
        pass
    return aside_n


def _move(src, dst, aside):
    """`src` to `dst`: one rename when `dst` is absent, else _merge_tree. Returns the count kept aside."""
    if not os.path.lexists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            _note_tree(src, dst)
        else:
            _note(src, dst)
        try:
            os.rename(src, dst)
        except OSError:
            pass
        else:
            if os.path.isdir(dst):
                _LANDED.extend(os.path.join(d, n) for d, _, names in os.walk(dst) for n in names)
            else:
                _LANDED.append(dst)
            return 0
    return _merge_tree(src, dst, aside)


def _rewrite_paths(p, moved):
    """Lines of .gitignore or .gitattributes that name an earlier place are made to name its place in the layout:
    `moved` maps each earlier path to its new one. True when the file changed."""
    try:
        with open(p, encoding="utf-8", newline="") as f:
            text = f.read()
    except OSError:
        return False
    new = _rewrite_text(text, moved)
    if new == text:
        return False
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    return True


def _rewrite_text(text, moved):
    """_rewrite_paths on a file's text -> the new text. A rewritten line the text already holds is dropped, so a seed
    block appended again in the earlier form leaves no line twice."""
    lines = text.splitlines(keepends=True)
    have = {l.strip() for l in lines}
    out = []
    for line in lines:
        s = line.lstrip()
        lead = line[:len(line) - len(s)]
        neg = "!" if s.startswith("!") else ""
        s = s[len(neg):]
        slash = "/" if s.startswith("/") else ""
        body = s[len(slash):]
        for old in sorted(moved, key=len, reverse=True):         # recall/models before models
            if body.startswith(old + "/") or body.rstrip("\r\n") == old:
                body = moved[old] + body[len(old):]
                new = lead + neg + slash + body
                if new.strip() in have:
                    new = None                                   # already there: the old form goes
                else:
                    have.add(new.strip())
                break
        else:
            new = line
        if new is not None:
            out.append(new)
    return "".join(out)


def _git(p4, *args):
    try:
        return subprocess.run(["git", "-C", p4, *args], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None


def _own_repo(p4):
    r = _git(p4, "rev-parse", "--show-toplevel")
    return bool(r and r.returncode == 0 and _same(r.stdout.decode("utf-8", "replace").strip(), p4))


def migrate_layout(p4, commit=True):
    """Move what lies in an earlier place of the layout into its plugin's folder: memory/, scratchpad/, tmp/ and src/
    into temportal/, and store/ and models/, at the top or under recall/, and archive/ into phi/. .gitignore and
    .gitattributes are rewritten to match, and when `p4` is a git repository of its own the move is committed alone.
    After a move, and at a store's first start, when it has no RECORD yet, keep_settings brings Claude Code's settings
    in the project's local file to what the store wants. Returns the lines to print, none when there was nothing to
    move. Cheap when there is nothing: one lstat call per earlier place in OLDER, one more for a move an earlier start
    renamed and did not commit, and one for the record."""
    lines = _migrate_layout(p4, commit)
    if (lines or not os.path.exists(record_path(p4))) and os.path.isdir(p4):
        project = session_project(p4)
        if project:
            try:
                keep_settings(project, p4=p4)
            except Exception as e:  # noqa: BLE001 — the layout move stands whatever the settings check meets
                lines = list(lines) + [f"Claude Code's settings not kept: {type(e).__name__}: {e}"]
    return lines


def _migrate_layout(p4, commit):
    if not _olds(p4) and not os.path.isfile(_pending_path(p4)):
        return []
    lock = os.path.join(p4, LAYOUT_LOCK)
    if not _take(lock):
        return []                                       # another hook moved it, or is still at it
    try:
        return _migrate(p4, commit)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def _take(lock, wait_s=5.0, stale_s=120.0):
    """The layout lock, or False once another hook held it for `wait_s`, since the hooks of a start run at once.
    The wait stays well under the 10-second timeout of the shortest hook that reaches it, retrieval's, so that hook
    still has time for its own work."""
    end, waited = time.monotonic() + wait_s, False
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            if not waited or _olds(os.path.dirname(lock)):
                return True
            os.remove(lock)                             # the hook that held it moved everything
            return False
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > stale_s:
                    os.remove(lock)
                    continue
            except OSError:
                continue
        except OSError:
            return False
        if time.monotonic() > end:
            return False
        waited = True
        time.sleep(0.1)


def _olds(p4):
    """[(kind, earlier path)] of every earlier place that still holds something, oldest first."""
    out = []
    for k, places in OLDER.items():
        for rel in places:
            p = os.path.join(p4, *rel.split("/"))
            if os.path.lexists(p) and not is_link(p):
                out.append((k, rel))
    return out


# A move is recorded before each rename, in the store's git directory, which no commit holds: a start killed in the
# renames or before the commit leaves the record, and the next start finishes the move and commits it. The commit is
# built from the record alone, each moved file taking the blob HEAD holds for it at its earlier place, in an index of
# its own, so git's clean filter runs only on the files no commit held before, which are hashed in one call, no change
# made to a tracked file between two starts is taken in, and the record goes only once HEAD has the commit.
PENDING = "p4-layout-pending.jsonl"
_JOURNAL = []                                       # the open record of the move under way, when the store is a repo


def _git_dir(p4):
    """The store's git directory, read from .git without running git: the folder itself, or the one a .git file
    names, as a worktree's does. None when there is none."""
    g = os.path.join(p4, ".git")
    if os.path.isdir(g):
        return g
    try:
        with open(g, encoding="utf-8") as f:
            line = f.readline().strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    d = line[len("gitdir:"):].strip()
    return os.path.normpath(d if os.path.isabs(d) else os.path.join(p4, d))


def _pending_path(p4):
    g = _git_dir(p4)
    return os.path.join(g, PENDING) if g else os.path.join(p4, ".git", PENDING)


def _note(src, dst):
    """Record that `src` moves to `dst`, or goes when `dst` is None, before it happens."""
    if not _JOURNAL:
        return
    p4, f = _JOURNAL[0], _JOURNAL[1]
    rel = lambda p: os.path.relpath(p, p4).replace("\\", "/")
    f.write(json.dumps({"m": [rel(src), rel(dst) if dst else None]}) + "\n")
    f.flush()


def _note_tree(src, dst):
    """Record every file of the folder `src` as moving to the same place under `dst`."""
    if not _JOURNAL:
        return
    for d, _dirs, names in os.walk(src):
        for n in names:
            s = os.path.join(d, n)
            _note(s, os.path.join(dst, os.path.relpath(s, src)))


def _note_blob(p4, name, moved):
    """Record the blob of .gitignore or .gitattributes as HEAD holds it with only the layout's rewrite applied, so an
    edit not yet committed stays out of the layout commit. Nothing is recorded when HEAD lacks the file or the
    rewrite changes nothing in it."""
    if not _JOURNAL:
        return
    r = _git(p4, "show", f"HEAD:{name}")
    if not (r and r.returncode == 0):
        return
    text = r.stdout.decode("utf-8", "surrogateescape")
    new = _rewrite_text(text, moved)
    if new == text:
        return
    try:
        r = subprocess.run(["git", "-C", p4, "hash-object", "-w", "--stdin"], capture_output=True, timeout=30,
                           input=new.encode("utf-8", "surrogateescape"))
    except (OSError, subprocess.SubprocessError):
        return
    sha = r.stdout.decode("ascii", "replace").strip() if r.returncode == 0 else ""
    if sha:
        _JOURNAL[1].write(json.dumps({"b": [name, sha]}) + "\n")
        _JOURNAL[1].flush()


def _commit_journal(p4):
    """Commit what the record holds and nothing else -> True once HEAD has it, or when there is nothing to commit; the
    record is removed then and kept otherwise."""
    rec = _pending_path(p4)
    try:
        with open(rec, encoding="utf-8", errors="replace") as f:
            lines = [l for l in f if l.strip()]
    except OSError:
        return False
    rows = []
    for l in lines:
        try:
            row = json.loads(l)
        except ValueError:
            continue                                    # a line a cut start left half written
        if isinstance(row, dict):
            rows.append(row)
    head = _git(p4, "rev-parse", "-q", "--verify", "HEAD")
    if not (head and head.returncode == 0):
        os.remove(rec)                                  # no commit yet: nothing is tracked to move
        return True
    head = head.stdout.decode("ascii").strip()
    r = _git(p4, "ls-tree", "-r", "-z", "--full-tree", "HEAD")
    if not (r and r.returncode == 0):
        return False
    tree = {}
    for item in r.stdout.decode("utf-8", "surrogateescape").split("\0"):
        if item:
            meta, path = item.split("\t", 1)
            mode, _kind, sha = meta.split()
            tree[path] = (mode, sha)
    over, fresh = {}, []
    look = lambda p: over[p] if p in over else tree.get(p)
    for row in rows:
        if "m" in row:
            src, dst = row["m"]
            done = os.path.lexists(os.path.join(p4, dst)) if dst else not os.path.lexists(os.path.join(p4, src))
            if not done:
                continue                                # noted, and the start was cut before the rename
            e = look(src)
            if e is None:
                if dst:
                    fresh.append(dst)                   # a file git did not track: committed at its new place
                continue
            over[src] = None
            if dst:
                over[dst] = e
        elif "b" in row:
            name, sha = row["b"]
            over[name] = ((look(name) or ("100644", ""))[0], sha)
    # what no commit held before, such as rows an older plugin wrote at an earlier place, is hashed as it stands, in
    # one git call, unless the store ignores it
    fresh = [p for p in dict.fromkeys(fresh) if p not in over and os.path.isfile(os.path.join(p4, p))]
    if fresh:
        r = _git_in(p4, ["check-ignore", "-z", "--stdin"], fresh)
        if not (r and r.returncode in (0, 1)):
            return False                                # which files are caches is not known: the record waits
        skip = set(r.stdout.decode("utf-8", "surrogateescape").split("\0"))
        fresh = [p for p in fresh if p not in skip]
    if fresh:
        try:
            r = subprocess.run(["git", "-C", p4, "hash-object", "-w", "--stdin-paths"], capture_output=True,
                               timeout=60, input="\n".join(fresh).encode("utf-8", "surrogateescape"))
        except (OSError, subprocess.SubprocessError):
            return False
        shas = r.stdout.decode("ascii", "replace").split() if r.returncode == 0 else []
        if len(shas) != len(fresh):
            return False
        over.update({p: ("100644", sha) for p, sha in zip(fresh, shas)})
    changes = {p: e for p, e in over.items() if e != tree.get(p)}
    if not changes:
        os.remove(rec)
        return True
    index = rec + ".index"
    env = dict(os.environ, GIT_INDEX_FILE=index, GIT_AUTHOR_NAME="p4", GIT_AUTHOR_EMAIL="p4@localhost",
               GIT_COMMITTER_NAME="p4", GIT_COMMITTER_EMAIL="p4@localhost")
    info = "".join(f"{e[0]} {e[1]}\t{p}\0" if e else f"0 {'0' * 40}\t{p}\0" for p, e in sorted(changes.items()))
    run = lambda *a, inp=None: subprocess.run(["git", "-C", p4, *a], input=inp, capture_output=True, env=env,
                                                timeout=60)
    try:
        steps = [run("read-tree", "HEAD"), run("update-index", "-z", "--index-info",
                                               inp=info.encode("utf-8", "surrogateescape"))]
        if any(s.returncode for s in steps):
            return False
        t = run("write-tree")
        c = run("commit-tree", t.stdout.decode().strip(), "-p", head, "-m",
                "layout: each plugin's files in .claude/p4/<plugin>/") if t.returncode == 0 else t
        if c.returncode:
            return False
        if run("update-ref", "HEAD", c.stdout.decode().strip(), head).returncode:
            return False
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        try:
            os.remove(index)
        except OSError:
            pass
    # the store's own index takes the new entries of the moved paths, and only them
    _git_in(p4, ["reset", "-q", "--pathspec-from-file=-", "--pathspec-file-nul"], sorted(changes))
    os.remove(rec)
    return True


def _git_in(p4, args, paths):
    try:
        return subprocess.run(["git", "-C", p4, *args], input="\0".join(paths).encode("utf-8", "surrogateescape"),
                              capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None


def _migrate(p4, commit):
    lines, done = [], {}
    del _LANDED[:]
    _STORE[:] = [p4] if _own_repo(p4) else []
    # the ignore rules first, so a cache is known as one at its new place before anything moves; the lines of every
    # earlier place are rewritten, whether it holds files or not, since a seed block may be appended again in the
    # earlier form
    places = {old: LAYOUT[k] for k, olds in OLDER.items() for old in olds}
    own = commit and _own_repo(p4)
    if own:
        try:
            _JOURNAL[:] = [p4, open(_pending_path(p4), "a", encoding="utf-8")]
        except OSError:
            pass
    try:
        _moves(p4, places, lines, done)
    finally:
        if _JOURNAL:
            _JOURNAL[1].close()
            del _JOURNAL[:]
    if own and os.path.isfile(_pending_path(p4)):
        _commit_journal(p4)
    return lines


def _moves(p4, places, lines, done):
    for f in (".gitignore", ".gitattributes"):
        _note_blob(p4, f, places)
        _rewrite_paths(os.path.join(p4, f), places)
    for k, rel in _olds(p4):
        src, dst = os.path.join(p4, *rel.split("/")), sub(p4, k)
        plugin = LAYOUT[k].split("/")[0]
        aside = os.path.join(p4, plugin, LAYOUT_CONFLICTS, k)
        try:
            a = _move(src, dst, aside)
        except OSError as e:
            lines.append(f"could not move {rel}/ to {LAYOUT[k]}/: {e}; tried again at the next start")
            continue
        done[rel] = LAYOUT[k]
        line = f"moved {rel}/ to {LAYOUT[k]}/"
        if a:
            line += f", differing files: {a}, kept in {plugin}/{LAYOUT_CONFLICTS}/"
        if os.path.lexists(src):
            line += ", some files left for the next start"
        lines.append(line)
    plugins = {v.split("/")[0] for v in LAYOUT.values()}
    for top in sorted({r.split("/")[0] for r in done if "/" in r} - plugins):   # recall/, once store/ and models/ left
        g = os.path.join(p4, top)
        kept = os.path.join(g, LAYOUT_CONFLICTS)
        if os.path.isdir(kept):
            there = os.path.join(p4, "phi", LAYOUT_CONFLICTS, top)
            _move(kept, there, there)
        try:
            os.rmdir(g)
        except OSError:
            pass
    if any(LAYOUT.get(k) == "temportal/notebook" and r == "temportal/scratchpad" for k, olds in OLDER.items()
           for r in olds if r in done):
        _carry_notebook(p4)
    # a move keeps each file's own time, so a set-aside copy older than its cache rule would be cleared by the
    # retention sweep of the same start, unreported: every file landed in a set-aside folder takes the move's time
    for p in _LANDED:
        if LAYOUT_CONFLICTS in p.replace("\\", "/").split("/"):
            try:
                os.utime(p)
            except OSError:
                pass


def _carry_notebook(p4):
    """After the notebook moved from temportal/scratchpad to temportal/notebook: each cookie of
    temportal/expires.json and each cache rule of p4.json's temportal.cache set on a scratchpad/ path is set on
    the same notebook/ path."""
    old, new = "scratchpad", "notebook"

    def moved(k):
        return new + k[len(old):] if isinstance(k, str) and (k == old or k.startswith(old + "/")) else k
    exp = os.path.join(p4, "temportal", "expires.json")
    d = read_json(exp)
    if d and any(moved(k) != k for k in d):
        replace_text(exp, json.dumps({moved(k): v for k, v in d.items()}, indent=1, sort_keys=True,
                                     ensure_ascii=False) + "\n")
    conf = read_json(path(p4))
    cache = ((conf or {}).get("temportal") or {}).get("cache")
    if isinstance(cache, dict) and any(moved(k) != k for k in cache):
        conf["temportal"]["cache"] = {moved(k): v for k, v in cache.items()}
        e = (conf.get(WRITTEN) or {}).get("temportal.cache")
        if isinstance(e, dict) and e.get("v") == cache:
            e["v"] = conf["temportal"]["cache"]         # written by load: still load's
        _write(p4, conf)


def _merge(base, over, unknown, prefix=""):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if prefix + k in RETIRED:
            continue
        if k not in base:
            if prefix + k not in READ_WHEN_SET:
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
    """Write p4.json through a temp file of this call's own, since the hooks of one event load at once."""
    fd, tmp = tempfile.mkstemp(prefix=FILE + ".", suffix=".tmp", dir=p4)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        os.replace(tmp, path(p4))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# The top-level key of p4.json where load keeps, for each default it wrote, the value and the GEN of the copy that
# wrote it, by the setting's dotted path. A value still equal to its entry was never set by hand. Only a copy with a
# higher GEN moves it to that copy's default, so two installed copies that differ on a default settle on the newer
# one's and never rewrite the file in turn. A value that differs from its entry was set by hand and is never moved.
WRITTEN = "_written"
# The generation of DEFAULTS: raised by one whenever a default changes, with the value it had added to HISTORY, so a
# store's written values follow the change. test_p4conf.py pins DEFAULTS to this number.
GEN = 9
# Past defaults by dotted path: a store from before the record whose value equals one of these, or today's default,
# counts that value as written by load, so it follows today's default.
HISTORY = {"recall.teacher.model": ["claude-fable-5-1"], "recall.lookups.web": ["answer"], "scratchpad.tmp": [True],
           "temportal.cache": [{"scratchpad/.out": {"max_age_days": 14, "max_mb": 500},
                                ".layout-conflicts": {"max_age_days": 30}}]}


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
    default or to a past one in HISTORY, as written at generation 0."""
    if isinstance(record, dict):
        return record
    out = {}
    for p, v in _leaves(DEFAULTS):
        have = _get(kept, p)
        if have is not _NONE and (have == v or have in HISTORY.get(p, ())):
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
    kept = {k: v for k, v in over.items() if k not in RETIRED}
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
    # a retired key alone never rewrites the file, since an older copy that still writes it would put it back at its
    # own next load: it leaves the file at the next rewrite for another reason
    if write and os.path.isdir(p4) and (not existed or out != _without_retired(over)):
        try:
            _write(p4, out)
        except OSError:
            pass
    return merged


def _without_retired(d, prefix=""):
    """`d` with every key of RETIRED left out, at any depth."""
    return {k: _without_retired(v, f"{prefix}{k}.") if isinstance(v, dict) else v for k, v in d.items()
            if prefix + k not in RETIRED}


def section(p4, name, write=True):
    return load(p4, write=write)[name]


def _at(d, dotted):
    for part in dotted.split("."):
        d = d.get(part, {}) if isinstance(d, dict) else {}
    return d


def apply(module_globals, values, names, defaults=None):
    """Set module constants from a section: names maps a setting to the constant it replaces. A value equal to its
    default leaves the constant as the code has it, since a test or a caller may have set it. A set-typed constant
    takes the list as a set."""
    for key, const in names.items():
        if key not in values or const not in module_globals:
            continue
        if defaults is not None and key in defaults and values[key] == defaults[key]:
            continue
        cur = module_globals[const]
        module_globals[const] = set(values[key]) if isinstance(cur, (set, frozenset)) else values[key]


def configure(module_globals, p4, dotted, names, write=True):
    """apply() from the section of p4.json at `dotted`, such as "recall.query", with the P4_* variables of person_env
    ahead of it; returns that section. A constant a variable set goes back to the value it had before once the
    variable is gone, since a process that runs hooks in turn keeps its module globals."""
    values = _at(load(p4, write=write), dotted)
    from_env = {k.split(".")[-1] for k in person_env(p4, warn=False) if k.rsplit(".", 1)[0] == dotted}
    saved = module_globals.get("_P4_ENV_SAVED") or {}
    for key, const in names.items():
        if const in saved:
            module_globals[const] = saved.pop(const)    # the code's own value, before any variable set it
        if key in from_env and const in module_globals:
            saved[const] = module_globals[const]
    if saved:
        module_globals["_P4_ENV_SAVED"] = saved
    else:
        module_globals.pop("_P4_ENV_SAVED", None)
    apply(module_globals, values, names, _at(DEFAULTS, dotted))
    return values


# --- p4's settings as P4_* variables ----------------------------------------------------------------------------------
# Every setting of DEFAULTS that steers behaviour, and each phi key of READ_WHEN_SET, has a variable: P4_ and its
# dotted path in upper case with each dot an underscore, such as P4_PHI_MAX_DEPTH for phi.max_depth, apart from the
# names of ENV_NAMES. p4.json stays p4's own source. keep_settings mirrors each setting a store changed from its
# default, and a READ_WHEN_SET key whenever the store sets it, under `env` of the project's local settings file, so the
# file shows every changed setting, and removes the entry once the setting is back at its default. Claude Code puts
# that block into the environment of every hook of a session, by env-vars.md, but a running session keeps the
# environment it started with, so a variable p4 wrote can be older than p4.json: load passes over every variable the
# ownership record says p4 wrote, now or before, and reads one ahead of p4.json only when a person set or changed it,
# in the local file or in the shell.
# Encoding, by env_text: a bool is 1 or 0, as the older switches P4_SCRATCHPAD_ASKS and P4_PHI_ISSUES take; a string
# is written as it is unless that text would read back as another value, and then as JSON; every other value is
# compact JSON. Decoding, by env_value: empty is unset; for a key that takes a bool, 1, 0, true and false in any case;
# else JSON, and the text itself for a key that takes a string. A value is checked as the key's reader in p4 takes it,
# by ENV_SCHEMA or the default's type, with the items of a list or an object, and anything that does not fit, or fails
# to read at all, is passed over with one stderr line, so the setting falls back to p4.json's value, which is the
# default unless the store changed it. A reader's own range check, such as phi.apply_caps, then keeps the default for a
# value out of range. A section of OPEN, temportal.cache, is merged over its default rules as p4.json's is. A variable
# only ever applies to the store of the session's own project, by env_applies.
ENV_PREFIX = "P4_"
ENV_SKIP = ("recall.updated",)            # who last set recall.inject and learn, and when: a record, not a setting
ENV_SET_ONLY = tuple(k for k in READ_WHEN_SET if k.startswith("phi."))
# A name the rule would give that an older variable of other meaning already has: P4_PHI_WATCH_S is puppeteer.py's
# tick for one run, used whether or not a session is busy, while phi.watch_s is the tick of a busy watcher only.
ENV_NAMES = {"phi.watch_s": "P4_PHI_WATCH_SECONDS"}
# What a key's reader takes where its default does not say: "num" a number, "strs" a list of strings, "rules" the
# lifetime rules of temportal.cache by folder, "levels" plans.child_levels' kinds, "inject" a bool or "rules-facts".
ENV_SCHEMA = {
    "phi.home": str, "recall.lookups.threshold": "num", "recall.teacher.cutoff": str,
    "phi.child_levels": "levels", "phi.puppeteer_section": str,
    "phi.clear_at": "num", "temportal.cache": "rules", "recall.inject": "inject",
}
# The strings a key's reader knows.
ENV_CHOICES = {"recall.said.mode": ("off", "shadow", "on"), "recall.lookups.web": ("note", "answer", "shadow", "off"),
               "recall.lookups.shell": ("note", "answer", "shadow", "off")}
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
    if spec == "rules":
        return isinstance(v, dict) and all(isinstance(r, dict) and all(isinstance(k, str) and _num(n)
                                                                      for k, n in r.items()) for r in v.values())
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


def env_text(key, v, default=_NONE):
    """The text env_value reads back as `v` for `key`."""
    tries = []
    if isinstance(v, bool):
        tries.append("1" if v else "0")
    if isinstance(v, str):
        tries.append(v)
    tries.append(json.dumps(v, ensure_ascii=False, separators=(",", ":")))
    for t in tries:
        got = env_value(key, t, default)
        if got is not _BAD and got is not _NONE and _same_json(got, v):
            return t
    return tries[-1]


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


def env_wants(p4):
    """{variable: text} of each setting store `p4` changes from its default in p4.json, read without the variables."""
    conf = _load_file(p4, write=False, warn=False)
    out = {}
    for key, default in env_keys().items():
        v = _get(conf, key)
        if v is _NONE or (default is not _NONE and _equal(v, default)):
            continue
        text = env_text(key, v, default)
        if env_value(key, text, default) is not _BAD:   # a value p4 would pass over is not written either
            out[env_name(key)] = text
    return out


def env_entries(p4, target, platform=None, environ=None):
    """None when the record is malformed, by env_written, so the keeper adds and removes no variable that run;
    else env_wants without each variable that is set elsewhere, which p4's entry in the local file would override: in
    this process's environment with a text p4 did not write, as the shell or another settings file gives it, or in the
    user, project or managed settings file beside `target`, as _elsewhere reads them for autoMemoryDirectory."""
    platform = platform or sys.platform
    environ = os.environ if environ is None else environ
    wrote = env_written(p4)
    if wrote is None:
        return None                                     # a malformed record: no variable can be told from p4's
    here = env_applies(p4)
    out = {}
    for name, text in env_wants(p4).items():
        if here and environ.get(name) and environ.get(name) not in wrote.get(name, ()):
            continue
        if _elsewhere(f"{ENV_KEY}.{name}", target, platform):
            continue
        out[name] = text
    return out


def _equal(a, b):
    """Equal as settings: 5 and 5.0 are, true and 1 are not."""
    nums = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b))
    return a == b if nums else _same_json(a, b)


# --- Claude Code's own settings, ezexe/p4#246 ---------------------------------------------------------------------
# p4 keeps the Claude Code settings it relies on in the project's `.claude/settings.local.json`, merged with what is
# there. What a store wants is the `claude` section of p4.json, read when set and never written by default:
# `autoMemoryDirectory` names the store's temportal/memory unless the section sets it false, and `attribution.commit`
# is written only when the section gives a text. Any other key the section names is never written: it is named with
# its value for ezexe, and a key of SECURITY is said to be ezexe's to decide. RECORD, in the store and kept out of its
# git by the seeded .gitignore, holds what p4 wrote into which file with the GEN of the copy that wrote it: a key still
# equal to its entry is p4's and may change at a higher GEN or go, a key that differs was set by hand and leaves the
# record, and a key the record owns that is missing from the file is written again. RECORD also holds what the
# watcher below last saw of Claude Code and the p4 plugins.
SECTION = "claude"
RECORD = "claude-settings.json"
SETTINGS_LOCK = ".settings.lock"
LOCAL = "settings.local.json"
WRITES = ("autoMemoryDirectory", "attribution.commit")
# disableAllHooks and disableSkillShellExecution are never written: they are defaults, writing them changes nothing,
# and a local false would override a true ezexe later sets in user or project settings. A key an earlier copy wrote
# and this one no longer owns is removed while it still holds the value written.
ENV_KEY = "env"                  # where the P4_* variables go: each one p4 owns is the dotted key env.<name>
# Raised by one whenever the keys this copy writes change, so a store's next start runs the whole check: the record
# holds the KEEPER of the copy that last ran it.
KEEPER = 5
PAST_MAX = 5                     # texts kept per variable of those p4 wrote and later replaced or removed
# The class of keys ezexe decides, by #246: every key of the topics "Permission settings", "Sandbox settings",
# "Authentication and providers" and "Enterprise and managed settings" of settings-reference.md, the table
# "Exceptions to managed settings precedence" of settings.md, and the keys named beside them. A dotted key under one
# of these is in the class too. ezexe's yes covers only what the keeper writes of it: the two allow rules, the ask
# rule on the archive tool, the deny rule on the model tool and p4's own P4_* variables under env; a store's `claude`
# section naming any key of the class is still told it is ezexe's to decide.
SECURITY = (
    "permissions", "sandbox", "autoMode", "allowManagedPermissionRulesOnly", "disableAutoMode",
    "useAutoModeDuringPlan", "skipAutoPermissionPrompt", "skipDangerousModePermissionPrompt",
    "allowedProviders", "apiKeyHelper", "awsAuthRefresh", "awsCredentialExport", "forceLoginMethod",
    "forceLoginGatewayUrl", "forceLoginOrgUUID", "gatewayInternalNetworks", "gcpAuthRefresh", "otelHeadersHelper",
    "disableSideloadFlags", "forceRemoteSettingsRefresh", "managedSourcesBehavior", "parentSettingsBehavior",
    "policyHelper", "wslInheritsWindowsSettings",
    "disableClaudeAiConnectors", "enableArtifact", "isolatePeerMachines", "remoteControlAtStartup",
    "crossSessionInbound", "syncClaudeAiSkills", "syncClaudeAiPlugins", "maxEffortLevel",
    "extraKnownMarketplaces", "env", "hooks", "disableAllHooks",
)
# Where the managed settings file sits on each platform, by the managed settings documentation.
MANAGED = {"win": ["C:/Program Files/ClaudeCode/managed-settings.json"],
           "darwin": ["/Library/Application Support/ClaudeCode/managed-settings.json"],
           "linux": ["/etc/claude-code/managed-settings.json"]}


def security(key):
    """True when `key`, dotted, is in the class of keys ezexe decides."""
    return any(key == s or key.startswith(s + ".") for s in SECURITY)


def record_path(p4):
    return os.path.join(p4, RECORD)


def read_json(p):
    """The JSON object at `p`; {} when it is missing; None when it is there and is not a JSON object."""
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _strs(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# The shape of each part of RECORD the keeper and the watcher read, kept by settings file where the part is one:
# a part, or one file's entry of it, of another shape is dropped by read_record.
_PER_FILE = {
    "files": lambda v: isinstance(v, dict),
    "p4past": lambda v: isinstance(v, dict),
    "kept": lambda v: isinstance(v, dict),
    "hand": _strs,
    "rules": lambda v: (isinstance(v, dict) and _strs(v.get("entries", [])) and _strs(v.get("hand", []))
                        and _int(v.get("gen", 0))),
    "askRules": lambda v: (isinstance(v, dict) and _strs(v.get("entries", [])) and _strs(v.get("hand", []))
                           and _int(v.get("gen", 0))),
    "denyRules": lambda v: (isinstance(v, dict) and _strs(v.get("entries", [])) and _strs(v.get("hand", []))
                            and _int(v.get("gen", 0))),
    "unreadable": lambda v: v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)),
}


def read_record(p4):
    """The record, with every part of a shape the keeper does not write dropped, so a record edited by hand never
    stops the keeper or the watcher: p4 then owns none of what that part held."""
    rec = read_json(record_path(p4)) or {}
    for k, ok in _PER_FILE.items():
        if k not in rec:
            continue
        if not isinstance(rec[k], dict):
            rec.pop(k)
            continue
        for name in [n for n, v in rec[k].items() if not ok(v)]:
            rec[k].pop(name)
    if "asked" in rec and not isinstance(rec["asked"], dict):
        rec.pop("asked")
    if "claude" in rec and not isinstance(rec["claude"], dict):
        rec.pop("claude")
    owed = rec.get("changelog")
    if "changelog" in rec and not (isinstance(owed, dict) and isinstance(owed.get("from"), str)
                                   and isinstance(owed.get("to"), str)):
        rec.pop("changelog")
    seen = rec.get("claude") or {}
    if "binaries" in seen and not (isinstance(seen["binaries"], dict)
                                   and all(isinstance(b, dict) for b in seen["binaries"].values())):
        seen.pop("binaries")
    if "path" in seen and not isinstance(seen["path"], str):
        seen.pop("path")
    for owned in (rec.get("files") or {}).values():
        for key in [x for x, e in owned.items() if not _entry(e)]:
            owned.pop(key)
    for texts_of in (rec.get("p4past") or {}).values():
        for name in [n for n, t in texts_of.items() if not _strs(t)]:
            texts_of.pop(name)
    return rec


def replace_text(p, text, tries=5):
    """Write `text` to `p` through a temp file in the same folder and os.replace, retried while another process holds
    the file on Windows."""
    d = os.path.dirname(p)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(p) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        for i in range(tries):
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                if i == tries - 1:
                    raise
                time.sleep(0.05 * (i + 1))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def write_record(p4, rec):
    replace_text(record_path(p4), json.dumps(rec, indent=1, ensure_ascii=False) + "\n")


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


def _flat(d, prefix=""):
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict) and v:
            out.update(_flat(v, f"{prefix}{k}."))
        else:
            out[prefix + k] = v
    return out


def _del(d, dotted):
    parts = dotted.split(".")
    chain = [d]
    for part in parts[:-1]:
        d = d.get(part) if isinstance(d, dict) else None
        if not isinstance(d, dict):
            return
        chain.append(d)
    chain[-1].pop(parts[-1], None)
    for parent, part in zip(reversed(chain[:-1]), reversed(parts[:-1])):
        if parent.get(part) == {}:
            parent.pop(part)                            # a section p4 emptied goes with its last key


def _same_value(key, a, b):
    if key == "autoMemoryDirectory" and isinstance(a, str) and isinstance(b, str):
        return _norm(os.path.expanduser(a)) == _norm(os.path.expanduser(b))
    return a == b


def _config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def _elsewhere(key, target, platform):
    """[(file, value)] of `key` in the user, project and managed settings files, each a file Claude Code reads beside
    the local one, so a local value would override the choice they hold."""
    files = [os.path.join(_config_dir(), "settings.json"), os.path.join(os.path.dirname(target), "settings.json")]
    files += next((v for k, v in MANAGED.items() if platform.startswith(k)), [])
    out = []
    for f in files:
        v = _get(read_json(f) or {}, key)
        if v is not _NONE and v is not None:
            out.append((f, v))
    return out


def wants(p4, target, platform=None):
    """({key: value or None}, {key: value}, the section, [(file, value)]): the keys of WRITES p4 keeps in `target`,
    None for one it wants gone, and `env.<name>` for each P4_* variable of env_wants; the other keys the store's
    `claude` section names, which are never written; the whole section; and each other file that names another
    memory folder."""
    platform = platform or sys.platform
    conf = _flat(load(p4, write=False, warn=False).get(SECTION) or {})
    out = {}
    mem = fwd(sub(p4, "memory"))
    other = [(f, v) for f, v in _elsewhere("autoMemoryDirectory", target, platform)
             if not _same_value("autoMemoryDirectory", v, mem)]
    out["autoMemoryDirectory"] = mem if conf.get("autoMemoryDirectory", True) is not False and not other else None
    text = conf.get("attribution.commit")
    out["attribution.commit"] = text if isinstance(text, str) else None
    for name, text in (env_entries(p4, target, platform) or {}).items():
        out[f"{ENV_KEY}.{name}"] = text
    return out, {k: v for k, v in conf.items() if k not in WRITES and k not in OWN_KEYS}, conf, other


def default_memory(project):
    """Claude Code's own auto memory folder for `project`, `<config>/projects/<slug>/memory`, the slug made from the
    main checkout's path as memory.md describes, or CLAUDE_CODE_PROJECT_DIR_NAME where CLAUDE_CONFIG_DIR is set."""
    name = os.environ.get("CLAUDE_CODE_PROJECT_DIR_NAME") if os.environ.get("CLAUDE_CONFIG_DIR") else None
    slug = name or re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(main_root(project)[0]))
    return os.path.join(_config_dir(), "projects", slug, "memory")


def carry_memory(src, dst):
    """Copy each file of `src` that `dst` lacks into `dst`, before autoMemoryDirectory points Claude Code at `dst`.
    Nothing is deleted. A file of the same name that differs keeps `dst`'s copy, and `src`'s copy goes beside it as
    `<name>.default<ext>`. Returns the number of files copied or set aside."""
    import shutil
    n = 0
    if not os.path.isdir(src) or _norm(src) == _norm(dst):
        return 0
    for d, _dirs, names in os.walk(src):
        for name in names:
            s = os.path.join(d, name)
            t = os.path.join(dst, os.path.relpath(s, src))
            try:
                if os.path.exists(t):
                    if filecmp.cmp(s, t, shallow=False):
                        continue
                    stem, ext = os.path.splitext(t)
                    t = f"{stem}.default{ext}"
                    if os.path.exists(t):
                        continue
                os.makedirs(os.path.dirname(t), exist_ok=True)
                shutil.copy2(s, t)
                n += 1
            except OSError:
                continue
    return n


# The two allow rules ezexe approved for p4 to keep in the local file, so a session runs the p4 commands its hook
# text names without a prompt: phi.py with any arguments, and p4.py sync. On Windows the same two in the PowerShell
# form too. Each rule is one entry of `permissions.allow` that
# p4 owns, recorded under RECORD's `rules` with the GEN of the copy that wrote it: p4 adds and removes only its own
# entries, never reorders or drops another, and replaces one when the plugin folder moves, only on a start and only at
# a GEN at least the entry's, so two plugin versions running at once never take each other's entries away. An entry
# deleted by hand is recorded by its identity, the tool form, the script and its arguments without the folder, and
# never written back, wherever the plugin folder moves. Only p4-phi's copy, which sits beside phi.py and so knows the
# path phi.py prints, writes them; the copy in p4-temportal leaves them as they are. The store's `claude` section sets
# `allowRules` false to have p4 remove its entries.
ALLOW_KEY = "permissions.allow"
OWN_KEYS = ("allowRules",)
PHI_SCRIPTS = None               # the folder of phi.py the rules name; None: this file's own folder, when phi.py is there
_RULE = re.compile(r'^(\w+)\(python -I -X utf8 "(?:.*/)?([^/"]+)"(.*)\)$')


def allow_rules(platform, conf):
    """The allow rules p4 wants, [] for none, or None when this copy cannot tell which and leaves them."""
    if conf.get("allowRules", True) is False:
        return []
    here = PHI_SCRIPTS or os.path.dirname(os.path.abspath(__file__))
    if not os.path.isfile(os.path.join(here, "phi.py")):
        return None
    s = fwd(here)
    cmds = [f'python -I -X utf8 "{s}/phi.py" *', f'python -I -X utf8 "{s}/p4.py" sync *']
    out = [f"Bash({c})" for c in cmds]
    if platform.startswith("win"):
        out += [f"PowerShell({c})" for c in cmds]
    return out


# The ask rule ezexe approved for p4 to keep in the local file of every project where p4 runs: an explicit ask rule
# prompts in every permission mode, bypassPermissions included, so the app shows its approval card before every
# archive_session call, which replaced p4-phi's own archive guard. permission-modes.md, "Actions no mode
# auto-approves". It is one entry of `permissions.ask` that p4 owns, kept by the same rule as the allow rules under
# RECORD's `askRules`: an entry the user wrote is never taken over or removed, and one deleted by hand stays gone.
# Both copies write it, since its text names no plugin folder.
ASK_KEY = "permissions.ask"
ASK_RULES = ("mcp__ccd_session_mgmt__archive_session",)
# The deny rule ezexe approved, kept the same way under RECORD's `denyRules`: a session's model is chosen on its start
# call and never changed after, since a change mid-run re-prices its turns, so set_session_model is denied, which
# replaced p4-phi's own refusal of the call. https://code.claude.com/docs/en/permissions: "Deny rules prevent Claude
# Code from using the specified tool", and "Rules are evaluated in order: deny, then ask, then allow."
DENY_KEY = "permissions.deny"
DENY_RULES = ("mcp__ccd_session_mgmt__set_session_model",)


def rule_identity(rule):
    """A rule of p4's without its folder: `Bash phi.py *`; the rule itself when it is not of p4's form."""
    m = _RULE.match(rule if isinstance(rule, str) else "")
    return f"{m.group(1)} {m.group(2)}{m.group(3)}" if m else rule


def _keep_rules(new, rec, name, wanted, owned_only, key=ALLOW_KEY, part="rules"):
    """p4's own entries of the list `key`, `permissions.allow` or `permissions.ask`, in `new` brought to `wanted`; the
    record's `part` kept in step. At a ConfigChange, `owned_only`, an entry gone from the file is recorded as deleted by
    hand and nothing else moves."""
    rules = rec.setdefault(part, {})
    mine = dict(rules.get(name) or {})
    entries, hand = list(mine.get("entries") or []), list(mine.get("hand") or [])
    gen = mine.get("gen", 0) if isinstance(mine.get("gen", 0), int) else 0
    cur = _get(new, key)
    if cur is not _NONE and not isinstance(cur, list):
        return                                          # not a list: left as it is
    have = list(cur) if cur is not _NONE else []
    for e in [e for e in entries if e not in have]:
        entries.remove(e)                               # deleted by hand: never written back, wherever it moves
        hand.append(rule_identity(e))
    if wanted is not None and not owned_only:
        mine_now = {rule_identity(e): e for e in entries}
        if GEN >= gen:
            for e in [e for e in entries if e not in wanted and rule_identity(e) not in map(rule_identity, wanted)]:
                have.remove(e)                          # p4's own, no longer wanted: only that entry goes
                entries.remove(e)
                mine_now.pop(rule_identity(e), None)
        for w in wanted:
            ident = rule_identity(w)
            old = mine_now.get(ident)
            if old == w or ident in hand:
                continue
            if old is not None:
                if GEN >= gen:                          # the plugin folder moved: the entry in place, replaced
                    have[have.index(old)] = w
                    entries[entries.index(old)] = w
                continue
            if any(rule_identity(h) == ident for h in have):
                continue                                # the user's own rule, or another copy's: left as it is
            have.append(w)
            entries.append(w)
        gen = max(gen, GEN)
    if have != (cur if cur is not _NONE else []):
        _put(new, key, have)
    if entries or hand:
        rules[name] = {"entries": entries, "hand": list(dict.fromkeys(hand)), "gen": gen}
    else:
        rules.pop(name, None)
    if not rules:
        rec.pop(part, None)


def _take_lock(lock, wait_s=3.0, stale_s=60.0):
    end = time.monotonic() + wait_s
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > stale_s:
                    os.remove(lock)
                    continue
            except OSError:
                continue
        except OSError:
            return False
        if time.monotonic() > end:
            return False
        time.sleep(0.05)


def keep_settings(project, platform=None, owned_only=False, p4=None, note=None, tell=False):
    """Bring the Claude Code settings p4 owns in the local file of a session started in `project` to what the store
    wants, under the store's SETTINGS_LOCK. `owned_only`, at a ConfigChange, looks only at the keys the record owns.
    `note`, such as the Claude Code binary the watcher saw, is merged into the record under the same lock. Returns
    {"file": the local file, "wrote": True when it was written, "asks": with `tell`, the lines for ezexe, each said
    once and recorded as said: a key a store wants that p4 never writes, and another file's memory folder}."""
    platform = platform or sys.platform
    project = os.path.abspath(project)
    p4 = p4 or os.path.join(main_root(project)[0], ".claude", "p4")
    target = settings_file(project, platform)
    out = {"file": target, "wrote": False, "asks": []}
    if not os.path.isdir(p4):
        return out
    lock = os.path.join(p4, SETTINGS_LOCK)
    if not _take_lock(lock):
        return out
    try:
        _keep(p4, project, target, platform, owned_only, out, note or {}, tell)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass
    return out


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return None


def _keep(p4, project, target, platform, owned_only, out, note, tell):
    rec = read_record(p4)
    before = json.dumps(rec, sort_keys=True)
    name = fwd(target)
    data = read_json(target)
    if data is None:
        if (rec.get("unreadable") or {}).get(name) != _mtime(target):
            print(f"p4: {target} is not a JSON object; p4's Claude Code settings left out, the file left as it is",
                  file=sys.stderr)
        # recorded with the file's time, so the check runs again only once the file changes
        rec.setdefault("unreadable", {})[name] = _mtime(target)
        rec.update(note)
        if not owned_only:
            rec["section"] = _flat(load(p4, write=False, warn=False).get(SECTION) or {})
            rec.setdefault("kept", {})[name] = {"keeper": KEEPER, "p4env": env_entries(p4, target, platform)}
        if json.dumps(rec, sort_keys=True) != before or not os.path.exists(record_path(p4)):
            write_record(p4, rec)
        return
    (rec.get("unreadable") or {}).pop(name, None)
    if not rec.get("unreadable"):
        rec.pop("unreadable", None)
    existed = os.path.exists(target)
    files = rec.setdefault("files", {})
    owned = dict(files.get(name) or {})
    hand = dict(rec.get("hand") or {})
    gone = list(hand.get(name) or [])
    want, others, conf, other = wants(p4, target, platform)
    new = copy.deepcopy(data)
    frozen = env_written(p4) is None                   # a malformed record: every P4_* entry left as it is
    p4env = None if frozen else {k.split(".", 1)[1]: v for k, v in want.items() if k.startswith(ENV_KEY + ".")}
    past = {n: list(t) for n, t in ((rec.get("p4past") or {}).get(name) or {}).items()}
    # in the order of the reference file: the two keys, p4's allow rules, its ask and deny rules, then the variables;
    # then each key an earlier copy wrote that this one no longer owns, such as disableAllHooks, which goes
    env = [k for k in want if k.startswith(ENV_KEY + ".")]
    env += [k for k in owned if k.startswith(ENV_KEY + ".") and k not in env]
    if frozen or not isinstance(new.get(ENV_KEY, {}), dict):
        env = []                                        # an `env` that is not an object: left as it is
    dropped = [k for k in owned if k not in WRITES and not k.startswith(ENV_KEY + ".")]
    rec.pop("keeper", None)                             # one KEEPER and P4_* record per store, before "kept"
    rec.pop("p4env", None)
    for k in WRITES:
        _keep_key(p4, project, new, k, want.get(k), owned, gone, owned_only)
    _keep_rules(new, rec, name, allow_rules(platform, conf), owned_only)
    _keep_rules(new, rec, name, list(ASK_RULES), owned_only, ASK_KEY, "askRules")
    _keep_rules(new, rec, name, list(DENY_RULES), owned_only, DENY_KEY, "denyRules")
    for k in env + dropped:
        _keep_key(p4, project, new, k, want.get(k), owned, gone, owned_only, past)
    cur_env = new.get(ENV_KEY) if isinstance(new.get(ENV_KEY), dict) else {}
    for n in list(past):                                # a person who wrote one of those texts again owns it now
        if not (owned.get(f"{ENV_KEY}.{n}") or {}).get("v") == cur_env.get(n):
            past[n] = [t for t in past[n] if t != cur_env.get(n)]
        if not past[n]:
            past.pop(n)
    if past:
        rec.setdefault("p4past", {})[name] = past
    else:
        (rec.get("p4past") or {}).pop(name, None)
        if not rec.get("p4past"):
            rec.pop("p4past", None)
    if new != data:
        replace_text(target, json.dumps(new, indent=2, ensure_ascii=False) + "\n")
        out["wrote"] = True
        if not existed:
            exclude_local(target)
        back = read_json(target) or {}
        for k, e in owned.items():
            if _get(back, k) != e.get("v"):
                print(f"p4: {target} lost {k} after p4 wrote it", file=sys.stderr)
    if owned:
        files[name] = owned
    else:
        files.pop(name, None)
    if gone:
        hand[name] = list(dict.fromkeys(gone))
        rec["hand"] = hand
    rec.update(note)
    if not owned_only:
        rec["section"] = conf
        rec.setdefault("kept", {})[name] = {"keeper": KEEPER, "p4env": p4env}
    if tell:
        told = rec.get("asked") or {}
        for k, v in others.items():
            if told.get(k) != v:
                out["asks"].append(
                    f"`{k}` set to {json.dumps(v, ensure_ascii=False)} in the store's p4.json is left unwritten: "
                    + ("it is a permission or security key, which ezexe decides" if security(k)
                       else "p4 writes only " + " and ".join(f"`{w}`" for w in WRITES)))
        if others:
            rec["asked"] = others
        else:
            rec.pop("asked", None)
        seen = [[fwd(f), v] for f, v in other]
        if seen and rec.get("otherMemory") != seen:
            f, v = other[0]
            out["asks"].append(f"`autoMemoryDirectory` in {fwd(f)} names {v}, so Claude Code loads auto memory from "
                               f"there and not from the store's {fwd(sub(p4, 'memory'))}")
        if seen:
            rec["otherMemory"] = seen
        else:
            rec.pop("otherMemory", None)
    if not files:
        rec.pop("files", None)
    if json.dumps(rec, sort_keys=True) != before or not os.path.exists(record_path(p4)):
        write_record(p4, rec)


def _keep_key(p4, project, new, k, d, owned, gone, owned_only, past=None):
    """Key `k` of the local file `new` brought to `d`, None for gone, by the record's rule: a key p4 owns that is
    deleted or changed by hand leaves the record for good, one a newer copy wrote is left to it, and an unowned key is
    written only where it is missing. An unowned key that already holds p4's value is taken as p4's, apart from a
    P4_* variable, which a person wrote and keeps: p4 never takes it and never removes it. A variable p4 replaces or
    removes goes into `past`, since a running session still holds it."""
    cur, e = _get(new, k), _entry(owned.get(k))
    variable = k.startswith(ENV_KEY + ".")
    if e and variable and past is not None and isinstance(e[0], str) and (
            cur is _NONE or cur != e[0] or (e[1] <= GEN and (d is None or cur != d))):
        n = k.split(".", 1)[1]                          # deleted or changed by hand, replaced or removed by p4
        past[n] = (past.get(n, []) + [e[0]])[-PAST_MAX:]
    if e:
        if cur is _NONE:
            owned.pop(k)                                # deleted by hand: no longer p4's, never written back
            gone.append(k)
        elif cur != e[0]:
            owned.pop(k)                                # set by hand: no longer p4's, never touched again
        elif e[1] > GEN:
            pass                                        # a newer copy wrote it: left to that copy
        elif d is None:
            _del(new, k)
            owned.pop(k)
        elif not _same_value(k, cur, d):
            _put(new, k, d)
            owned[k] = {"v": d, "gen": GEN}
    elif d is not None and not owned_only and k not in gone:
        if cur is _NONE:
            if k == "autoMemoryDirectory":              # what Claude Code wrote in its own folder comes along first
                carry_memory(default_memory(project), sub(p4, "memory"))
            _put(new, k, d)
            owned[k] = {"v": d, "gen": GEN}
        elif _same_value(k, cur, d) and not variable:
            owned[k] = {"v": cur, "gen": GEN}          # the value p4 would write: p4's from now


def exclude_local(target):
    """Add `.claude/settings.local.json` to the repository's info/exclude when git does not already ignore the file
    p4 created, as settings.md asks of a file made by hand."""
    root = os.path.dirname(os.path.dirname(target))
    r = _git(root, "check-ignore", "-q", target)
    if r is None or r.returncode != 1:
        return False                                    # ignored already, or not in a repository
    r = _git(root, "rev-parse", "--git-path", "info/exclude")
    if not (r and r.returncode == 0 and r.stdout.strip()):
        return False
    path = r.stdout.decode("utf-8", "replace").strip()
    path = path if os.path.isabs(path) else os.path.join(root, path)
    try:
        text = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                text = f.read()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(("" if not text or text.endswith("\n") else "\n") + ".claude/settings.local.json\n")
    except OSError:
        return False
    return True


# --- The watcher, ezexe/p4#246 -------------------------------------------------------------------------------------
# p4-phi's hook.py runs watch() at every SessionStart, from its layout handler, and at a ConfigChange of a settings
# file, and at a start runs read_changelog, which reads what the record owes from Claude Code's own cached changelog.
MARKET = "p4-marketplace"


def _version(v):
    out = []
    for part in str(v or "").split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


SETTINGS_ENV = "P4_PHI_SETTINGS"          # 0 turns the settings watcher off
VERSION_S = 2.0                           # what one `--version` may take, inside the layout hook's 15 s
# claude-directory.md, "Kept until you delete them": "`cache/changelog.md` | Cached copy of the Claude Code changelog,
# shown by `/release-notes`. Refreshed in the background." It is a path under `~/.claude/`, which CLAUDE_CONFIG_DIR
# moves. p4 fetches no changelog of its own. What that copy lacks is the search for WATCHED and a record of the
# versions read, and it can be older than the binary that runs, so the record keeps the versions still owed.
CHANGELOG_CACHE = ("cache", "changelog.md")
WATCH_PAGE = ("phi", "claude-code-watch.md")
WATCH_PENDING = ("phi", "claude-code-watch.pending.json")
CONFIG_SOURCES = ("local_settings", "project_settings", "user_settings")
# The documented defaults p4 relies on, each with the issue to act on when the changelog names it.
WATCHED = {
    "autoMemoryDirectory": "ezexe/p4#246", "autoMemoryEnabled": "ezexe/p4#246",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "ezexe/p4#246", "MEMORY.md": "ezexe/p4#92",
    "blockReadsOutsideWorkingDirectories": "ezexe/p4#246", "blockWritesOutsideWorkingDirectories": "ezexe/p4#246",
    "additionalDirectories": "ezexe/p4#246", "settings.local.json": "ezexe/p4#246", "attribution": "ezexe/p4#246",
    "includeCoAuthoredBy": "ezexe/p4#246", "cleanupPeriodDays": "ezexe/p4#131",
    "desktopSessionCleanupPeriodDays": "ezexe/p4#131", "enableArtifact": "ezexe/p4#131",
    "scratchpad_dir": "ezexe/p4#131", "CLAUDE_PID": "ezexe/p4#246", "10,000 characters": "ezexe/p4#243",
    "CLAUDE_CODE_STOP_HOOK_BLOCK_CAP": "ezexe/p4#246", "BASH_DEFAULT_TIMEOUT_MS": "ezexe/p4#243",
    "ConfigChange": "ezexe/p4#246", "SessionStart": "ezexe/p4#246", "crossSessionInbound": "ezexe/p4#246",
}


def exe_of_pid(pid):
    """The executable path of process `pid`: QueryFullProcessImageNameW on Windows, /proc/<pid>/exe on Linux and
    `ps -o comm=` elsewhere; None when it cannot be read."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                   ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k32.OpenProcess(0x1000, False, int(pid))            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            buf, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
            return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
        finally:
            k32.CloseHandle(h)
    try:
        return os.readlink(f"/proc/{int(pid)}/exe")
    except (OSError, ValueError):
        pass
    try:
        r = subprocess.run(["ps", "-o", "comm=", "-p", str(int(pid))], capture_output=True, text=True, timeout=2)
        p = r.stdout.strip()
        return p if r.returncode == 0 and os.path.isabs(p) else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def claude_binary():
    """(path, weak) of the Claude Code binary running this session: the process CLAUDE_PID names when it is a
    `claude` executable, or `claude` on the PATH, a weaker reading since the desktop app runs its own copy. The PATH
    serves when CLAUDE_PID is unset, as before v2.1.214, unreadable, or names another program, such as `node` for an
    npm install, which is never run with --version. (None, True) when neither is found."""
    pid = os.environ.get("CLAUDE_PID")
    if pid and pid.isdigit():
        try:
            p = exe_of_pid(int(pid))
        except (OSError, ValueError, AttributeError):
            p = None
        if p and os.path.isfile(p) and os.path.splitext(os.path.basename(p))[0].lower() == "claude":
            return p, False
    import shutil
    return shutil.which("claude"), True


def read_version(path):
    """The version `<path> --version` prints, '' when it prints none in VERSION_S."""
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=VERSION_S,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"\d+\.\d+\.\d+", r.stdout or "")
    return m.group(0) if m else ""


def plugin_versions(project):
    """{name: version} of the p4 plugins installed for `project`, the highest of each, from Claude Code's
    installed_plugins.json: an install at user scope, or one scoped to this project."""
    out = {}
    data = (read_json(os.path.join(_config_dir(), "plugins", "installed_plugins.json")) or {}).get("plugins") or {}
    for key, rows in data.items():
        name, _, market = str(key).partition("@")
        if market != MARKET:
            continue
        for r in rows if isinstance(rows, list) else [rows]:
            if not isinstance(r, dict) or not r.get("version"):
                continue
            if r.get("scope") in ("local", "project") and _norm(r.get("projectPath") or "") != _norm(project):
                continue
            if name not in out or _version(r["version"]) > _version(out[name]):
                out[name] = r["version"]
    return out


def section_of(p4):
    """The `claude` section of the store's p4.json as it stands, read without load's merge."""
    return _flat((read_json(path(p4)) or {}).get(SECTION) or {})


def _binaries(seen):
    """The record's binaries by path; a record from before they were kept by path holds one at its top."""
    got = dict(seen.get("binaries") or {})
    if seen.get("path") and seen["path"] not in got:
        got[seen["path"]] = {k: seen.get(k) for k in ("size", "mtime", "version", "weak")}
    return got


def watch(project, payload):
    """At every SessionStart: the cheap comparison of the running Claude Code binary, the p4 plugins' versions, the
    store's `claude` section, a local file left unread, the memory folder other files name, and, for this
    session's own local file, the KEEPER of the copy that last kept it and the P4_* variables p4.json asks for, with
    the record; any change runs keep_settings. Each binary is kept by its path, so the desktop app's copy and the
    `claude` command used in turn are each read once. At a ConfigChange of a settings file: keep_settings on the
    keys the record owns.
    A newer Claude Code than any the record holds leaves the versions between the two in the record's `changelog`
    part, as the sections read_changelog owes. Returns {"asks": the lines for ezexe}."""
    out = {"asks": []}
    if os.environ.get(SETTINGS_ENV) == "0":
        return out
    p4 = os.path.join(main_root(project)[0], ".claude", "p4")
    if not os.path.isdir(p4):
        return out
    if payload.get("hook_event_name") == "ConfigChange":
        if payload.get("source") in CONFIG_SOURCES:
            keep_settings(project, owned_only=True, p4=p4)
        return out
    rec = read_record(p4)
    seen = rec.get("claude") or {}
    binaries = _binaries(seen)
    note = {}
    binary, weak = claude_binary()
    if binary:
        try:
            st = os.stat(binary)
        except OSError:
            st = None
        known = binaries.get(binary) or {}
        if st and (known.get("size"), known.get("mtime")) != (st.st_size, st.st_mtime):
            v = read_version(binary) or known.get("version") or ""
            binaries[binary] = {"size": st.st_size, "mtime": st.st_mtime, "version": v, "weak": weak}
            top = seen.get("version") or ""
            note["claude"] = {"binaries": binaries, "version": max((top, v), key=_version), "path": binary}
            if v and top and _version(v) > _version(top):
                note["changelog"] = {"from": (rec.get("changelog") or {}).get("from") or top, "to": v}
    plugins = plugin_versions(project)
    if plugins != (rec.get("plugins") or {}):
        note["plugins"] = plugins
    target = settings_file(project)
    unread = (rec.get("unreadable") or {}).get(fwd(target), "none")
    other = [[fwd(f), v] for f, v in _elsewhere("autoMemoryDirectory", target, sys.platform)
             if not _same_value("autoMemoryDirectory", v, fwd(sub(p4, "memory")))]
    if (not note and section_of(p4) == rec.get("section") and unread in ("none", _mtime(target))
            and other == (rec.get("otherMemory") or [])
            and ((rec.get("kept") or {}).get(fwd(target)) or {})
            == {"keeper": KEEPER, "p4env": env_entries(p4, target)}):
        return out
    out["asks"] = keep_settings(project, p4=p4, note=note, tell=True)["asks"]
    return out


def watched_terms(limits=None):
    """{term: issue}: WATCHED, and the `terms` of every entry of claude_code_limits.json, each with its issue. A
    missing or unreadable file adds nothing."""
    out = dict(WATCHED)
    try:
        with open(limits or "", encoding="utf-8") as f:
            rows = json.load(f)
    except (OSError, ValueError):
        rows = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        issue = f"{r.get('repo') or 'ezexe/p4'}#{r.get('issue')}" if r.get("issue") else (r.get("repo") or "")
        for t in r.get("terms") or []:
            if isinstance(t, str) and t.strip():
                out.setdefault(t.strip(), issue)
    return out


def changelog_hits(text, old, new, terms):
    """[(term, version, issue, line)] for each watched term in the `## <version>` sections after `old` up to `new`."""
    import re
    hits, ver = [], None
    lo, hi = _version(old), _version(new)
    for line in text.splitlines():
        m = re.match(r"^##\s+v?(\d+\.\d+\.\d+)", line)
        if m:
            ver = m.group(1) if lo < _version(m.group(1)) <= hi else None
            continue
        if not ver:
            continue
        low = line.lower()
        for term, issue in terms.items():
            if term.lower() in low:
                hits.append((term, ver, issue, line.strip().lstrip("-* ").strip()[:300]))
    return hits


def changelog_cache():
    """Claude Code's own cached copy of its changelog, under its configuration folder."""
    return os.path.join(_config_dir(), *CHANGELOG_CACHE)


def changelog_top(text):
    """The newest version among the `## <version>` headings of a changelog, '' when it has none."""
    import re
    found = re.findall(r"(?m)^##\s+v?(\d+\.\d+\.\d+)", text or "")
    return max(found, key=_version) if found else ""


def read_changelog(p4, text=None, limits=None):
    """Read the sections the record's `changelog` part owes, after its `from` up to its `to`, from Claude Code's
    cached changelog, and write each hit of a watched term to the store's watch page and to its pending file, which
    the next prompt's hook hands a session line by line. The cached copy can be older than the binary that runs, so
    only the sections it holds are read and the record then owes the rest, from the newest version read; a missing
    copy reads nothing and owes all of it. A copy with the time and size of the last read is not opened again. All of
    it runs under the store's SETTINGS_LOCK, so the record never loses what the keeper writes. Returns the hits."""
    owed = read_record(p4).get("changelog")
    if not owed:
        return []
    seen = None
    if text is None:
        try:
            st = os.stat(changelog_cache())
            seen = [st.st_mtime, st.st_size]
        except OSError:
            pass
        if seen is None or owed.get("seen") == seen:
            return []
    lock = os.path.join(p4, SETTINGS_LOCK)
    if not _take_lock(lock):
        return []
    try:
        rec = read_record(p4)
        owed = rec.get("changelog")
        if not owed:
            return []
        if text is None:
            try:
                with open(changelog_cache(), encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                return []
        old, new = owed["from"], owed["to"]
        top = changelog_top(text)
        upto = min(top, new, key=_version) if top else old
        hits = _note_changelog(p4, old, upto, text, limits) if _version(upto) > _version(old) else []
        if _version(upto) >= _version(new):
            rec.pop("changelog")
        else:
            rec["changelog"] = {"from": max(old, upto, key=_version), "to": new, "seen": seen}
        write_record(p4, rec)
        return hits
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def _note_changelog(p4, old, new, text, limits):
    """The hits between `old` and `new`, written to the watch page and the pending file."""
    hits = changelog_hits(text, old, new, watched_terms(limits))
    page = os.path.join(p4, *WATCH_PAGE)
    os.makedirs(os.path.dirname(page), exist_ok=True)
    head = "" if os.path.exists(page) else (
        "# Claude Code changes p4 watches\n\nEach section is one read of Claude Code's changelog after a new version"
        " ran here, by p4conf.py's watcher.\n")
    body = f"\n## {time.strftime('%Y-%m-%d %H:%M')}, {old} to {new}\n\n"
    body += "".join(f"- `{t}` in {v}, act on {i}: {l}\n" for t, v, i, l in hits) or "- No watched term.\n"
    with open(page, "a", encoding="utf-8", newline="\n") as f:
        f.write(head + body)
    if hits:
        pend = os.path.join(p4, *WATCH_PENDING)
        have = (read_json(pend) or {}).get("lines") or []
        lines = have + [f"phi (p4-phi): Claude Code {v} changed `{t}` by its changelog; read that entry and "
                        f"{os.path.join(*WATCH_PAGE)} in the store, and act on {i}." for t, v, i, _ in hits]
        replace_text(pend, json.dumps({"lines": list(dict.fromkeys(lines))}, ensure_ascii=False) + "\n")
    return hits


def claim_watch(p4):
    """The pending watch lines, taken by one rename so one session gets each once; [] when there are none."""
    pend = os.path.join(p4, *WATCH_PENDING)
    mine = f"{pend}.{os.getpid()}"
    try:
        os.replace(pend, mine)
    except OSError:
        return []
    try:
        return [l for l in (read_json(mine) or {}).get("lines") or [] if isinstance(l, str)]
    finally:
        try:
            os.remove(mine)
        except OSError:
            pass
