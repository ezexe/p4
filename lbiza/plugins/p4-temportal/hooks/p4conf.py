"""
p4conf.py: the settings of every p4 plugin, kept in one file of the store, `<project>/.claude/p4/p4.json`.

Each plugin carries its own copy of this file, since an installed plugin cannot import another plugin's code, and
test_p4conf.py holds the copies the same byte for byte. `load(p4)` returns DEFAULTS with the file merged over them.
It writes the file when it is missing, seeded from `phi/models/config.json` when that file exists, and when it lacks
a key of DEFAULTS, keeping every value already there. A file that is not valid JSON is never overwritten: the defaults
are used and a line goes to stderr. p4conf reads no environment variable: a plugin that lets one win over its
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
        "top_orchestrates": True,        # false: a top-level session does its plan itself, no child unless asked
        "levels": True,                  # false: no delegation rule, and no long command moved to the background
        "file_sets": True,               # false: a session may be started by a brief that declares no write set
        "session_archives": False,       # true: a session may archive itself or another session
        "issues": True,                  # false: no issue is filed for the purpose of a child session that writes
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
            "variant_weight": 0.5, "expand_weight": 0.5,
        },
        "train": {
            "candidates": 200, "train_neg": 60, "folds": 5, "floor_drop": 0.02, "min_precision": 0.6,
            "first_floor": 0.36, "owed_labels": 10, "owed_age_s": 3600, "max_tasks": 400,
        },
        "teacher": {
            "model": "claude-fable-5-1", "second_opinion": "claude-opus-5-5", "cutoff": None, "effort": "high",
            "max_tokens": 16000, "agree_min": 0.65, "newer_max": 12, "cand_k": 60, "dict_batch": 20,
        },
    },
}

# Sections whose keys are ezexe's to choose: merged over the defaults, never called unknown.
OPEN = ("temportal.cache",)

# Top-level keys no plugin reads: never returned or called unknown, and dropped from p4.json when it is rewritten for
# another reason.
RETIRED = ("plans", "version")

# The keys of phi/models/config.json, a settings file nothing writes, and where p4.json keeps each value.
LEGACY = {"teacher-model": ("recall", "teacher", "model"), "teacher-cutoff": ("recall", "teacher", "cutoff"),
          "inject": ("recall", "inject")}


# Where each kind of file lives in the store, by plugin. p4-temportal keeps the auto memory, the notebook, the
# session scratchpad directories and saved code in temportal/, and p4-phi keeps its session tree and the retrieval
# corpus and models in phi/. p4.json and the store's own git files stay at the top: .git, .github, .gitignore and
# .gitattributes.
LAYOUT = {
    "memory": "temportal/memory",
    "scratchpad": "temportal/scratchpad",
    "tmp": "temportal/tmp",
    "src": "temportal/src",
    "store": "phi/store",
    "models": "phi/models",
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
                    os.replace(s, t)
                    _LANDED.append(t)
                elif os.path.isfile(t) and filecmp.cmp(s, t, shallow=False):
                    os.remove(s)
                elif _ignored(t):
                    # a cache git ignores: the newer stays, the older goes, and nothing is set aside to be committed
                    if os.path.getmtime(s) > os.path.getmtime(t):
                        os.replace(s, t)
                    else:
                        os.remove(s)
                else:
                    old = t if os.path.getmtime(s) > os.path.getmtime(t) else s
                    a = os.path.join(aside, r)
                    os.makedirs(os.path.dirname(a), exist_ok=True)
                    if os.path.lexists(a):
                        a += time.strftime(".%Y%m%d-%H%M%S")
                    os.replace(old, a)
                    _LANDED.append(a)
                    if old is t:
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
    `moved` maps each earlier path to its new one. A rewritten line the file already holds is dropped, so a seed block
    appended again in the earlier form leaves no line twice. True when the file changed."""
    try:
        with open(p, encoding="utf-8", newline="") as f:
            text = f.read()
    except OSError:
        return False
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
    new = "".join(out)
    if new == text:
        return False
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    return True


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
    into temportal/, and store/ and models/, at the top or under recall/, into phi/. .gitignore and .gitattributes are
    rewritten to match, and when `p4` is a git repository of its own the move is committed alone. Returns the lines
    to print, none when there was nothing to move. Cheap when there is nothing: eight lstat calls."""
    if not _olds(p4):
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


def _take(lock, wait_s=15.0, stale_s=120.0):
    """The layout lock, or False once another hook held it for `wait_s`, since the hooks of a start run at once."""
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


def _tracked(p4, rel):
    """The files git tracks under `rel`, as git names them."""
    r = _git(p4, "ls-files", "-z", "--", rel)
    return [x for x in r.stdout.decode("utf-8", "surrogateescape").split("\0") if x] if r and r.returncode == 0 else []


def _commit_moves(p4, gone, landed, extra):
    """Commit the move and nothing else: the removal of `gone`, the tracked files of the earlier places, the files
    that `landed` in a new place, and `extra`, the rewritten .gitignore and .gitattributes. What else the hooks left
    pending stays pending. A landed file the store ignores is left out, as git would leave it."""
    rel = lambda p: os.path.relpath(p, p4).replace("\\", "/")
    new = sorted({rel(p) for p in landed if os.path.isfile(p)})
    if new:
        r = _git_in(p4, ["check-ignore", "-z", "--stdin"], new)
        skip = set(r.stdout.decode("utf-8", "surrogateescape").split("\0")) if r else set()
        new = [p for p in new if p not in skip]
    paths = sorted(set(gone) | set(new) | set(extra))
    if not paths:
        return
    _git_in(p4, ["add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul"], paths)
    _git_in(p4, ["-c", "user.name=p4", "-c", "user.email=p4@localhost", "commit", "-q", "--no-verify", "--only",
                 "-m", "layout: each plugin's files in .claude/p4/<plugin>/",
                 "--pathspec-from-file=-", "--pathspec-file-nul"], paths)


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
    changed = [f for f in (".gitignore", ".gitattributes") if _rewrite_paths(os.path.join(p4, f), places)]
    own = commit and _own_repo(p4)
    gone = [f for _, rel in _olds(p4) for f in _tracked(p4, rel)] if own else []
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
    if own and done:
        _commit_moves(p4, gone, _LANDED, changed)
    return lines


def _merge(base, over, unknown, prefix=""):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k not in base:
            unknown.append(prefix + k)
            out[k] = v                   # kept, so a key a newer plugin copy wrote survives an older copy's rewrite
        elif prefix + k in OPEN and isinstance(base[k], dict) and isinstance(v, dict):
            out[k] = {**base[k], **v}    # keys of ezexe's choosing, such as a cache rule per folder
        elif isinstance(base[k], dict) and isinstance(v, dict):
            out[k] = _merge(base[k], v, unknown, f"{prefix}{k}.")
        else:
            out[k] = v
    return out


def _legacy(p4):
    """The values of phi/models/config.json, placed where p4.json keeps them."""
    try:
        with open(sub(p4, "models", "config.json"), encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        return {}
    over = {}
    for key, where in LEGACY.items():
        if isinstance(old, dict) and key in old:
            d = over
            for part in where[:-1]:
                d = d.setdefault(part, {})
            d[where[-1]] = old[key]
    return over


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


def load(p4, write=True, warn=True):
    """The merged settings. Writes p4.json when it is missing or lacks a default key, if `write` and `p4` exists."""
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
    else:
        over = _legacy(p4)
    over = {k: v for k, v in over.items() if k not in RETIRED}
    unknown = []
    merged = _merge(DEFAULTS, over, unknown)
    if warn and unknown:
        print(f"p4: {path(p4)} holds keys this plugin does not read, kept as they are: {', '.join(unknown)}",
              file=sys.stderr)
    # a retired key alone never rewrites the file, since an older copy that still writes it would put it back at its
    # own next load: it leaves the file at the next rewrite for a missing key
    if write and os.path.isdir(p4) and (not existed or merged != over):
        try:
            _write(p4, merged)
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
