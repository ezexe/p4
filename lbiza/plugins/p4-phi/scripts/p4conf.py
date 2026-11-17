"""
p4conf.py: the settings of every p4 plugin, kept in one file of the store, `<project>/.claude/p4/p4.json`.

Each plugin carries its own copy of this file, since an installed plugin cannot import another plugin's code, and
test_p4conf.py holds the copies the same byte for byte. `load(p4)` returns DEFAULTS with the file merged over them. It
writes the file when it is missing, when it lacks a key of DEFAULTS and when a default an older generation of this
file wrote has changed, keeping every value set by hand: WRITTEN records what it wrote. Two limits: a value set by
hand that equals the value load recorded as written moves at the next GEN, and in a store from before the record a
value set by hand that equals a past default in HISTORY moves. A file that is not valid JSON is never overwritten: the
defaults are used and a line goes to stderr. p4conf reads no environment variable: a plugin that lets one win over its
section for a run reads it itself.

It also holds the store's layout: each plugin writes in a folder of its own, `.claude/p4/<plugin>/`, beside p4.json
and the store's own git files. `sub(p4, name, ...)` is where a kind of file lives and `rel(name, ...)` the same path
as git names it. `migrate_layout(p4)` moves files from an earlier place of the layout into their plugin's folder.
Every plugin calls it at its start, so whichever plugin runs first moves them.
"""

import copy
import filecmp
import glob
import json
import os
import subprocess
import sys
import tempfile
import time

FILE = "p4.json"

DEFAULTS = {
    "memory": {
        "retries": 5,                    # attempts at deleting a file of the auto memory directory held open
        "retry_wait_s": 1.0,             # seconds between those attempts
    },
    "scratchpad": {
        "asks": False,                   # the two asks about where code belongs; P4_SCRATCHPAD_ASKS=1 or 0 wins
        "tmp": True,                     # the session scratchpad directory in temportal/tmp/<session>, linked from
                                         # the path Claude Code gives; P4_SCRATCHPAD_TMP=1 or 0 wins
        "tmp_idle_days": 7,              # another session's quiet scratchpad directory is committed and removed
        "tmp_max_file_mb": 20,           # a larger file in a scratchpad directory is never staged, so never removed
        "tmp_max_files": 5000,           # a scratchpad directory with more files is never committed or removed,
                                         # and only its tracked files' changes are staged
        "tmp_empty_idle_hours": 1,       # another session's empty scratchpad directory quiet this long is removed
        "scratch_sweep_minutes": 60,     # another session's empty scratchpad folder under the temp directory is
                                         # removed once quiet this long, and one with files is linked at once
        # folders a scratchpad directory never stages: caches and test trees, a trailing * matching a prefix
        "tmp_skip_dirs": [".pytest_cache", "node_modules", ".venv", "venv", ".tox", ".mypy_cache", "pytest-of-*"],
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
        "levels": True,                  # false: no delegation rule, and no long command moved to the background
        "file_sets": True,               # false: a session may be started by a brief that declares no write set
        "session_archives": False,       # true: a session may archive itself or another session
        "issues": True,                  # false: the issue loop is off: no open issue a brief names, no commit line
                                         # for it, no regression test at Stop and no push line
    },
    "temportal": {                       # lifetimes under .claude/p4/temportal/, read by p4-temportal's lifetime.py
        "cache": {                       # a rule per folder, relative to temportal/, and memory/ is never cleared
            "scratchpad/.out": {"max_age_days": 14, "max_mb": 500},   # the logs, build output and binaries moved here
            ".layout-conflicts": {"max_age_days": 30},                 # the older copies a layout move set aside
        },
    },
    "recall": {                          # p4-phi's retrieval
        "inject": "rules-facts",         # what reaches the model: false none, "rules-facts" only rule and fact lines,
                                         # true every line; P4_RECALL_INJECT=0, 1 or rules-facts wins for a run
        "learn": True,                   # false: the Stop hook trains nothing, and labels are still written
        "updated": None,                 # who last set inject and learn, and when: ezexe/phi's phi_model mode writes it
        "pinned_chars": 1500,
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
            "web": "answer",             # what an earlier finding for the same question does: "answer" in place of
            "shell": "shadow",           # the call, once, "note" beside the result, "shadow" logged only, or "off"
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
READ_WHEN_SET = ("phi.child_levels", "phi.puppeteer_section", "phi.puppeteer_chars")

# Top-level keys no plugin reads: never returned or called unknown, and dropped from p4.json when it is rewritten for
# another reason.
RETIRED = ("plans", "version")

# Where each kind of file lives in the store, by plugin. p4-temportal keeps the auto memory, the notebook, the session
# scratchpad directories and saved code in temportal/, and p4-phi keeps its session tree, the retrieval corpus and
# models, and the archive a migration from the per-session layout keeps verbatim in phi/. p4.json and the store's own
# git files stay at the top: .git, .github, .gitignore and .gitattributes.
LAYOUT = {
    "memory": "temportal/memory",
    "scratchpad": "temportal/scratchpad",
    "tmp": "temportal/tmp",
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
LAYOUT_LOCK = ".layout.lock"              # held while one hook moves the store; the others wait for it
LAYOUT_CONFLICTS = ".layout-conflicts"    # inside the plugin's folder: the older of two differing copies
TEMP_ROOTS = ("/tmp", "/private/tmp")     # beside tempfile.gettempdir(): where Claude Code makes its claude* folders


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


def _harness_links(sid):
    """The scratchpad paths Claude Code gave session `sid` that are links:
    `<temp>/claude*/<project>/<sid>/scratchpad`."""
    out, seen = [], set()
    for r in (tempfile.gettempdir(), *TEMP_ROOTS):
        key = os.path.normcase(os.path.realpath(r))
        if key in seen or not os.path.isdir(r):
            continue
        seen.add(key)
        for d in glob.glob(os.path.join(glob.escape(r), "claude*", "*", glob.escape(sid), "scratchpad")):
            if is_link(d):
                out.append(d)
    return out


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
                    # a cache git ignores: the newer stays, the older goes, and nothing is set aside to be committed
                    if os.path.getmtime(s) > os.path.getmtime(t):
                        _note(s, t)
                        os.replace(s, t)
                    else:
                        _note(s, None)
                        os.remove(s)
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


def _move_tmp(old, new, aside):
    """tmp/ at the top of the store into temportal/tmp/, one session at a time. A session whose scratchpad path is a
    link to its folder in tmp/ is linked to its new folder. Returns the count kept aside."""
    os.makedirs(new, exist_ok=True)
    n_aside = 0
    for sid in sorted(os.listdir(old)):
        o, n = os.path.join(old, sid), os.path.join(new, sid)
        links = [l for l in _harness_links(sid) if _same(l, o)] if os.path.isdir(o) else []
        for l in links:
            try:
                _unlink(l)
            except OSError:
                pass
        if os.path.isdir(o) and not is_link(o):
            n_aside += _move(o, n, os.path.join(aside, sid))
        elif os.path.isfile(o):
            n_aside += _move(o, n, aside)
        for l in links:
            if not os.path.lexists(l):
                try:
                    _make_link(l, n if os.path.isdir(n) else o)
                except OSError:
                    os.makedirs(l, exist_ok=True)       # Claude Code still finds a folder to write to
    try:
        os.rmdir(old)
    except OSError:
        pass
    return n_aside


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
    Returns the lines to print, none when there was nothing to move. Cheap when there is nothing: one lstat call per
    earlier place in OLDER, and one more for a move an earlier start renamed and did not commit."""
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
            a = _move_tmp(src, dst, aside) if k == "tmp" and os.path.isdir(src) else _move(src, dst, aside)
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
    for top in sorted({r.split("/")[0] for r in done if "/" in r}):    # recall/, once store/ and models/ left it
        g = os.path.join(p4, top)
        kept = os.path.join(g, LAYOUT_CONFLICTS)
        if os.path.isdir(kept):
            there = os.path.join(p4, "phi", LAYOUT_CONFLICTS, top)
            _move(kept, there, there)
        try:
            os.rmdir(g)
        except OSError:
            pass
    # a move keeps each file's own time, so a set-aside copy older than its cache rule would be cleared by the
    # retention sweep of the same start, unreported: every file landed in a set-aside folder takes the move's time
    for p in _LANDED:
        if LAYOUT_CONFLICTS in p.replace("\\", "/").split("/"):
            try:
                os.utime(p)
            except OSError:
                pass


def _merge(base, over, unknown, prefix=""):
    out = copy.deepcopy(base)
    for k, v in over.items():
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
GEN = 1
# Past defaults by dotted path: a store from before the record whose value equals one of these, or today's default,
# counts that value as written by load, so it follows today's default.
HISTORY = {"recall.teacher.model": ["claude-fable-5-1"]}


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


def load(p4, write=True, warn=True):
    """The merged settings. Writes p4.json when it is missing, lacks a default key or holds a default an older
    generation wrote, if `write` and `p4` exists. Under WRITTEN it records what it wrote and its GEN. A section of OPEN,
    such as temportal.cache, is one setting: when an older copy merges a rule a newer GEN dropped back into it, the
    section no longer equals its entry and counts as set by hand."""
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
    if write and os.path.isdir(p4) and (not existed or out != {k: v for k, v in over.items() if k not in RETIRED}):
        try:
            _write(p4, out)
        except OSError:
            pass
    return merged


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
    """apply() from the section of p4.json at `dotted`, such as "recall.query"; returns that section."""
    values = _at(load(p4, write=write), dotted)
    apply(module_globals, values, names, _at(DEFAULTS, dotted))
    return values
