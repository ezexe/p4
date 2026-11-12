"""
p4conf.py: every p4 plugin's settings in one file, `<project>/.claude/p4/p4.json`.

The same file is copied into each plugin (an installed plugin cannot import another's code); test_p4conf.py holds
the copies byte-identical. `load(p4)` returns DEFAULTS with the file merged over them, and writes the file when it is
missing (seeded from the retired models/config.json, if any) or lacks a key a newer version added, keeping every
value already there. A file that is not valid JSON is never overwritten: the defaults are used and a line goes to
stderr. Environment variables a plugin documents (P4_RECALL_INJECT, P4_SCRATCHPAD_ASKS) still win, for one run.

It also holds the store's layout: each plugin writes in a directory of its own, `.claude/p4/<plugin>/`, never flat in
`.claude/p4/`. `sub(p4, name, ...)` is where a kind of file lives, `rel(name, ...)` the same path as git names it, and
`migrate_layout(p4)` moves a store an older plugin wrote flat into the new layout. Every plugin calls it at its start,
so a store is moved by whichever plugin runs first.
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
VERSION = 1

DEFAULTS = {
    "version": VERSION,
    "memory": {
        "retries": 5,                    # attempts at a move AppData holds open
        "retry_wait_s": 1.0,
    },
    "scratchpad": {
        "asks": False,                   # the two asks about where code belongs (P4_SCRATCHPAD_ASKS=1 for one run)
        "tmp": True,                     # the session scratchpad as a link into .claude/p4/temportal/tmp/<session> (P4_SCRATCHPAD_TMP=0 for one run)
        "tmp_idle_days": 7,              # another session's tmp untouched this long is committed, then deleted
        "tmp_max_file_mb": 20,           # a larger tmp file is never staged, so never deleted
        "tmp_max_files": 5000,           # a tmp with more files is left alone
        "tmp_empty_idle_hours": 1,       # another session's empty tmp quiet this long is removed at a start
        "scratch_sweep_minutes": 60,     # another session's scratchpad quiet this long is linked, repaired or removed
        "tmp_skip_dirs": [".pytest_cache", "node_modules", ".venv", "venv", ".tox", ".mypy_cache", "pytest-of-*"],
        "ignorable_ext": ["log", "out", "tmp", "dump", "pid", "o", "obj", "pdb", "ilk", "exe", "dll", "lib", "so",
                          "dylib", "a", "class", "pyc", "pyo", "tlog", "binlog", "etl", "trace", "lastbuildstate"],
        "ignorable_dirs": ["bin", "build", "obj", "logs", "out", "dist", "target", "node_modules", "__pycache__",
                           ".cache", "cmake-build-debug", "cmake-build-release", "x64", "debug", "release"],
        "repo_uses_min_name": 6,         # a basename shorter than this matches too much to call it a use
        "repo_uses_max": 200,            # candidate names one git grep carries
        "repo_uses_lines": 10,           # lines printed at most; the rest counted on one more
    },
    "phi": {                             # the session tree (p4-phi)
        "home": None,                    # a home store's git remote: related repositories share one session tree
        "track": False,                  # phi/ committed in the store; off until no tracked file holds a local path
        "act_dont_wait": True,           # false: the built-in act-don't-wait rule is left out in this project
        "top_orchestrates": True,        # false: the top session lands its plan itself, no child unless asked
    },
    "temportal": {                       # lifetimes under .claude/p4/temportal/ (p4-temportal lifetime.py)
        "cache": {                       # a rule per directory, relative to temportal/; memory/ is never cleared
            "scratchpad/.out": {"max_age_days": 14, "max_mb": 500},   # swept logs, build output, binaries
            ".layout-conflicts": {"max_age_days": 30},                 # older copies a layout move kept aside
        },
    },
    "recall": {
        "inject": "rules-facts",         # false, "rules-facts" or true (P4_RECALL_INJECT=0|1|rules-facts for one run)
        "learn": True,                   # false: the Stop hook trains nothing (phi_model mode off); labels are still written
        "updated": None,                 # who last set inject/learn, and when (phi_model mode writes it)
        "pinned_chars": 1500,
        "repo_deadline_s": 8.0,
        "deps": {                        # frameworks, library packages and external modules as entries (deps.py)
            "auto": True,                # node_modules, vendor, third_party, _deps, vcpkg_installed, site-packages
            "roots": [],                 # more roots: paths relative to the project, or absolute (outside it)
            "deadline_s": 6.0,           # what one hook spends reading changed packages; the rest waits for the next
            "max_entries": 20000,
            "package_files": 3,          # files read of one package beyond those a session opened (deps.py FILES:
            "package_entries": 40,       # more of them measured worse on the ranker's silence and precision)
            "scan": 20000,               # directory entries one package's walk looks at
            "depth": 6,
        },
        "said": {                        # what a session states about the lines it was shown (said.py)
            "mode": "off",               # off | shadow (asked and written down) | on (training reads it too)
        },
        "lookups": {                     # every tool call recorded, and checked before the next one like it (lookups.py)
            "on": True,
            "web": "answer",             # an earlier finding for the same question: "answer" (in place of the call,
            "shell": "shadow",           # once), "note" (beside the result), "shadow" (logged only) or "off"
            "after": True,               # a failure other sessions met is told what they did about it
            "threshold": None,           # None: the trained threshold (0.6 before a first round)
            "min_precision": 0.85,       # how often an answered call must be right for a threshold to be taken
            "max_age_days": 30,          # an older finding is not handed back
            "finding_chars": 4000,       # kept of a web call's answer
            "shown_chars": 1500,         # shown of it
            "epochs_web": 30,            # training rounds of the web model, and passes of the
            "epochs_shell": 6,           # failure model (lookups.py: the sweep that set them)
        },
        "near": {                        # candidates from what earlier, similar tasks used (near.py)
            "on": True,
            "neighbours": 20,            # earlier tasks whose entries are taken
            "max": 100,                  # entries added to a task's candidates
            "same_session": False,       # the session's own earlier tasks too: scores well, tells it nothing
        },
        "node": {                        # the session tree (node.py, .docs/p4/recall-node.md)
            "on": False,                 # the entries the sessions above used: candidates, a feature in training
        },
        "sync": {                        # every machine's branch of the store kept in step (sync.py)
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

# Sections no plugin reads any more: dropped from a p4.json that still holds one. `plans` was the p4-plans
# plugin's; its two skills went back to the repositories that wrote them (2026-11-11), which state their own
# values, so no settings file holds any.
RETIRED = ("plans",)

LEGACY = {"teacher-model": ("recall", "teacher", "model"), "teacher-cutoff": ("recall", "teacher", "cutoff"),
          "inject": ("recall", "inject")}


# Where each kind of file lives under .claude/p4, by plugin. p4-temportal keeps what Claude Code would otherwise write
# under AppData or the system temp directory: memory, the notebook, the session scratchpads and saved code. p4-phi
# keeps phi/: its session tree, and recall's store and models, since recall is part of it. p4.json and the store
# repository's own files stay at the top: .git, .github, .gitignore and .gitattributes.
LAYOUT = {
    "memory": "temportal/memory",
    "scratchpad": "temportal/scratchpad",
    "tmp": "temportal/tmp",
    "src": "temportal/src",
    "store": "phi/store",
    "models": "phi/models",
}
# Where an older plugin kept each of them, oldest first: flat at the top before p4-temportal 0.2.0, and under recall/
# while p4-recall was a plugin of its own, 0.9.0 to 0.10.0. migrate_layout moves either.
OLDER = {k: [k] for k in LAYOUT}
OLDER["store"].append("recall/store")
OLDER["models"].append("recall/models")
LAYOUT_LOCK = ".layout.lock"              # held while one hook moves the store; the others wait for it
LAYOUT_CONFLICTS = ".layout-conflicts"    # inside the plugin's directory: the older of two differing copies
TEMP_ROOTS = ("/tmp", "/private/tmp")     # beside tempfile.gettempdir(): where the harness puts its claude*


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
    """The harness scratchpads of session `sid` that are links: `<temp>/claude*/<project>/<sid>/scratchpad`."""
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
    """True when the store's git ignores `path`: a cache, never set aside (L1)."""
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
                    # a cache git ignores (L1): the newer stays, the older goes, nothing is set aside to be committed
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
    """A flat tmp/ into the new one, session by session. A session whose harness scratchpad is a link to its old
    directory is linked to the new one. Returns the count kept aside."""
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
                    os.makedirs(l, exist_ok=True)       # the harness still finds a directory to write to
    try:
        os.rmdir(old)
    except OSError:
        pass
    return n_aside


def _rewrite_paths(p, moved):
    """Lines of .gitignore or .gitattributes that name an older place are made to name its new one: `moved` maps each
    old path to its new one. A rewritten line the file already holds is dropped, so an older plugin's seed block
    appended again leaves no line twice. True when the file changed."""
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
    """Move what an older plugin wrote in an older place into its plugin's directory: memory/, scratchpad/, tmp/ and
    src/ into temportal/, and store/ and models/, flat or under recall/, into phi/. .gitignore and .gitattributes are
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
    """The layout lock, or False once another hook held it for `wait_s` (the start's hooks run at once)."""
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
    """[(kind, older path)] of every older place that still holds something, oldest first."""
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
    """Commit the move and nothing else: the removal of `gone` (tracked files of the older places), the files that
    `landed` in a new place, and `extra` (.gitignore, .gitattributes). What else the hooks left pending stays
    pending. A landed file the store ignores is left out, as git would."""
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
    # the ignore rules first, so a cache is known as one at its new place before anything moves (L1); every older
    # place, moved now, before or never there, since an older plugin may append its line again (B3b)
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
            lines.append(f"could not move {rel}/ to {LAYOUT[k]}/ ({e}); tried again at the next start")
            continue
        done[rel] = LAYOUT[k]
        line = f"moved {rel}/ to {LAYOUT[k]}/"
        if a:
            line += f", {a} differing file(s) kept in {plugin}/{LAYOUT_CONFLICTS}/"
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
            out[k] = v                   # kept, so a newer plugin's key survives an older one's rewrite
        elif prefix + k in OPEN and isinstance(base[k], dict) and isinstance(v, dict):
            out[k] = {**base[k], **v}    # keys of ezexe's choosing, such as a cache rule per directory
        elif isinstance(base[k], dict) and isinstance(v, dict):
            out[k] = _merge(base[k], v, unknown, f"{prefix}{k}.")
        else:
            out[k] = v
    return out


def _legacy(p4):
    """The values of the retired models/config.json, placed where p4.json keeps them."""
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
    tmp = path(p4) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    os.replace(tmp, path(p4))


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
                print(f"p4: {path(p4)} unreadable ({e}); defaults used, the file left as it is", file=sys.stderr)
            return copy.deepcopy(DEFAULTS)
    else:
        over = _legacy(p4)
    had = dict(over)
    over = {k: v for k, v in over.items() if k not in RETIRED}
    unknown = []
    merged = _merge(DEFAULTS, over, unknown)
    if warn and unknown:
        print(f"p4: unknown key(s) in {path(p4)}, kept but unused: {', '.join(unknown)}", file=sys.stderr)
    if write and os.path.isdir(p4) and (not existed or merged != had):
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
    default leaves the constant as the code has it (a test or a caller may have set it). A set-typed constant
    takes the list as a set."""
    for key, const in names.items():
        if key not in values or const not in module_globals:
            continue
        if defaults is not None and key in defaults and values[key] == defaults[key]:
            continue
        cur = module_globals[const]
        module_globals[const] = set(values[key]) if isinstance(cur, (set, frozenset)) else values[key]


def configure(module_globals, p4, dotted, names, write=True):
    """apply() from the section at `dotted` (e.g. "recall.query") of p4.json; returns that section."""
    values = _at(load(p4, write=write), dotted)
    apply(module_globals, values, names, _at(DEFAULTS, dotted))
    return values
