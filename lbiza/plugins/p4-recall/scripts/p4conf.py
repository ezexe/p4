"""
p4conf.py: every p4 plugin's settings in one file, `<project>/.claude/p4/p4.json`.

The same file is copied into each plugin (an installed plugin cannot import another's code); test_p4conf.py holds
the copies byte-identical. `load(p4)` returns DEFAULTS with the file merged over them, and writes the file when it is
missing (seeded from the retired models/config.json, if any) or lacks a key a newer version added, keeping every
value already there. A file that is not valid JSON is never overwritten: the defaults are used and a line goes to
stderr. Environment variables a plugin documents (P4_RECALL_INJECT, P4_SCRATCHPAD_ASKS) still win, for one run.
"""

import copy
import json
import os
import sys

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
        "ignorable_ext": ["log", "out", "tmp", "dump", "pid", "o", "obj", "pdb", "ilk", "exe", "dll", "lib", "so",
                          "dylib", "a", "class", "pyc", "pyo", "tlog", "binlog", "etl", "trace", "lastbuildstate"],
        "ignorable_dirs": ["bin", "build", "obj", "logs", "out", "dist", "target", "node_modules", "__pycache__",
                           ".cache", "cmake-build-debug", "cmake-build-release", "x64", "debug", "release"],
        "repo_uses_min_name": 6,         # a basename shorter than this matches too much to call it a use
        "repo_uses_max": 200,            # candidate names one git grep carries
        "repo_uses_lines": 10,           # lines printed at most; the rest counted on one more
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
    "plans": {
        "owner_title": "the user",                     # who clears flights and closes plans
        "plans_dir": ".claude/plans",                  # plans in flight, relative to the project root
        "archive_branch": "plans",                     # complete/ and todo/; null: a finished plan is deleted
        "archive_worktree": ".claude/plans-archive",   # attached only for a move, removed the same turn
        "changelog": "CHANGELOG.md",
        "flights_dir": ".claude/p4/flights",
        "store_dir": ".claude/p4/store",
        "tests": {"build": None, "run": None},         # red/green's two cleared commands; {suite} is the filter
        "exclusive": [],                               # shared trees or long runs held one at a time
        "documented": [],                              # upstream docs a plan's decisions are checked against
        "code_style_rule": None,
        "reserved_models": ["fable"],
        "role_models": {
            "writer": "general-purpose/opus/medium",
            "integrator": "general-purpose/sonnet/medium",
            "cross_check": "general-purpose/sonnet/medium",
            "evidence_finder": "general-purpose/haiku/low",
        },
        "scratch_dir": None,
    },
}

LEGACY = {"teacher-model": ("recall", "teacher", "model"), "teacher-cutoff": ("recall", "teacher", "cutoff"),
          "inject": ("recall", "inject")}


def path(p4):
    return os.path.join(p4, FILE)


def _merge(base, over, unknown, prefix=""):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k not in base:
            unknown.append(prefix + k)
            out[k] = v                   # kept, so a newer plugin's key survives an older one's rewrite
        elif isinstance(base[k], dict) and isinstance(v, dict):
            out[k] = _merge(base[k], v, unknown, f"{prefix}{k}.")
        else:
            out[k] = v
    return out


def _legacy(p4):
    """The values of the retired models/config.json, placed where p4.json keeps them."""
    try:
        with open(os.path.join(p4, "models", "config.json"), encoding="utf-8") as f:
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
    unknown = []
    merged = _merge(DEFAULTS, over, unknown)
    if warn and unknown:
        print(f"p4: unknown key(s) in {path(p4)}, kept but unused: {', '.join(unknown)}", file=sys.stderr)
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
