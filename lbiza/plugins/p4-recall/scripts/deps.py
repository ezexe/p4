#!/usr/bin/env python3
"""deps.py: the project's frameworks, library packages and external modules as recall entries, `p4.py index --deps`.

repo.py indexes what the project tracks and leaves vendored trees out. This indexes what the project is built on:
each dependency root is read as packages, each package by its manifest, its documents and the surface a session
would open, and a package is read again only when it was installed or updated. The state lives in `models/deps.json`
(a cache, ignored by git: it holds this machine's paths); the entries join `models/index.json` beside the
repository's, so recall can serve them, the hooks label them from what a turn opened, and the ranker trains on them.

Roots (`recall.deps` of p4.json):
  auto    true: every directory named node_modules, vendor, third_party, _deps, vcpkg_installed or site-packages
          found within AUTO_DEPTH levels of the project root (dot directories are not entered, .venv and venv are)
  roots   more of them, each a path (relative to the project, or absolute: a tree outside the project, such as a
          framework's own checkout). A path inside another root names the part of it that matters: it is kept
          as a root of its own and read by its directories, each one a package, whatever manifest it carries

Packages of a root, by its name:
  node_modules     each <name>/package.json and @scope/<name>/package.json
  site-packages    each *.dist-info (name and version from the directory's name)
  _deps            each <name>-src (CMake FetchContent); -build, -subbuild and -tmp are build output
  anything else    the root itself when it carries a manifest (.git, package.json, CMakeLists.txt, DEPS, ...);
                   otherwise each directory in it, a directory with one of the names above read as that kind

A package's version is what it declares (package.json, dist-info, CMake's project(VERSION), a VERSION file,
pyproject/Cargo), then its git HEAD (in it or in its src/), then a *.sha256 beside or in it. Its signature is that
version and the names, sizes and times of its top-level files: when the signature moves, the package was installed
or updated, so it is read again, the change is recorded as an update entry (`<date> <name> <old> -> <new>`), and
train.py owes a round.

Entries of a package (ids in the repository's form, so the hooks' repo labels land on them):
  the package   repo:<path>                 `<path> <name> <version> <description>`
  its files     repo:<path>/<file>[#sym]    documents by heading, manifests by target, sources by top-level symbol
                (repo.file_entries), for FILES files at most, the shallowest and the public ones first (include/,
                public/, modules/, src/, lib/; an entry point package.json names), never tests, builds or binaries
  an update     dep-update:<sha8>           shown as a commit dated the day it was seen
A path inside the project is relative to it; a root outside it is shown as `@<root's name>/...`, and
`externals()` gives transcript.py the map back, so a file a turn opened there is labelled too.

A file a session opened in a package that the index does not hold is remembered (`note_opened`, from the close
hook) and read first, past the caps, at the next build: the entries follow what the sessions actually use.

Bounds: a package's files are read one directory at a time in turn, FILES at most (3 by default: the measured
setting, see FILES; a changed cap has every package read again); a package's walk stops after
SCAN entries or DEPTH levels; a transitive node or Python package (one the
project's own manifest does not name) gets its package entry and its README only; the whole stops at MAX_ENTRIES,
the most recently updated packages first; `build` stops at its deadline and goes on from there next time.
"""

import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ranker  # noqa: E402
import repo  # noqa: E402

STATE = "deps.json"
VERSION = 1
AUTO = True
ROOTS = []
DEADLINE_S = 6.0
MAX_ENTRIES = 20000
AUTO_NAMES = ("node_modules", "vendor", "third_party", "_deps", "vcpkg_installed", "site-packages")
AUTO_DEPTH = 3
ENTER_DOT = (".venv", "venv")
FILES, ENTRIES = 3, 40               # of a direct package: files read, entries kept. Measured on a store of 712
                                     # tasks (2026-11-10, p4.py eval on copies): with no dependency entries the
                                     # ranker printed for 9% of ordinary prompts and scored r-precision 0.044; with
                                     # these caps (409 entries) 13% and 0.038; with 400 files and 1,500 entries a
                                     # package (9,070 entries) 30% and 0.035. Only 39 of 2,222 repo labels fell on a
                                     # dependency file. So a package is its entry, its documents and what a session
                                     # opened in it; recall.deps.package_files raises it for a store that gains.
PER_FILE = 12                        # entries of one file: its path and its first symbols
LIGHT_FILES, LIGHT_ENTRIES = 2, 30   # of a transitive one
SCAN, DEPTH = 20000, 6
OPENED = 200                         # files a session opened in one package, remembered and always read
LISTED = 600                         # entries of a named folder's own files: read within the caps, the rest by name
USED = 400                           # files of one package the project's own sources include, always read
UP = 8                               # directories above a package an include path may start from
SOURCE_EXT = (".h", ".hh", ".hpp", ".hxx", ".inl", ".c", ".cc", ".cpp", ".cxx", ".m", ".mm", ".mojom")
SOURCE_BYTES = 262144
INCLUDE = re.compile(r'^[ \t]*(?:#[ \t]*(?:include|import)[ \t]*[<"]([^">\n]+)[">]|import[ \t]+"([^"\n]+)"[ \t]*;)', re.M)
MAX_UPDATES = 500
MANIFESTS = (".git", "package.json", "CMakeLists.txt", "DEPS", "pyproject.toml", "setup.py", "Cargo.toml", "go.mod",
             "BUILD.gn", "vcpkg.json", "VERSION", "VERSION.txt", "version.txt", "VERSION.in")
SKIP_DIRS = frozenset("""node_modules test tests testing __tests__ spec specs build out dist obj bin tmp temp target
debug release fixtures testdata test_data benchmarks benchmark coverage __pycache__ site-packages""".split())
PUBLIC_DIRS = ("include", "public", "modules", "src", "lib", "api", "docs")
DOC_NAMES = ("readme", "changelog", "change_list", "breaking_changes", "changes", "history", "news", "upgrading",
             "migration")
SIG_FILES = 64


def configure(p4):
    """recall.deps of the store's p4.json over the constants (read, never written, here)."""
    import p4conf
    p4conf.configure(globals(), p4, "recall.deps", {
        "auto": "AUTO", "roots": "ROOTS", "deadline_s": "DEADLINE_S", "max_entries": "MAX_ENTRIES",
        "package_files": "FILES", "package_entries": "ENTRIES", "scan": "SCAN", "depth": "DEPTH"}, write=False)


def sha8(s):
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:8]


def posix(p):
    return p.replace(os.sep, "/")


# --- roots -----------------------------------------------------------------------------------------------

def auto_roots(project):
    """Directories named in AUTO_NAMES within AUTO_DEPTH levels of the project; a found one is not entered."""
    out, level = [], [project]
    for _ in range(AUTO_DEPTH + 1):
        nxt = []
        for d in level:
            try:
                it = os.scandir(d)
            except OSError:
                continue
            with it:
                for e in it:
                    try:
                        if not e.is_dir(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    if e.name in AUTO_NAMES:
                        out.append(e.path)
                    elif not e.name.startswith(".") or e.name in ENTER_DOT:
                        nxt.append(e.path)
        level = nxt
    return out


def roots(project):
    """[(absolute root, the prefix its entries' paths carry, split)], the configured ones first. A found root inside
    another is dropped; a configured one inside another is kept, the owner's word that the part matters: it carries
    the outer root's prefix and its path below it, and is split (each of its directories a package of its own)."""
    found = []
    for r in ROOTS:
        r = os.path.expanduser(str(r))
        found.append(os.path.normpath(r if os.path.isabs(r) else os.path.join(project, r)))
    if AUTO:
        found += auto_roots(project)
    out, proj, seen, named = [], os.path.normpath(project), {}, len(ROOTS)
    for i, r in enumerate(found):
        if not os.path.isdir(r) or r in seen:
            continue
        outer = max((s for s in seen if r.startswith(s + os.sep)), key=len, default="")
        if outer and i >= named:
            continue
        inside = r.startswith(proj + os.sep)
        seen[r] = (seen[outer] + "/" + posix(r[len(outer) + 1:]) if outer else
                   posix(r[len(proj) + 1:]) if inside else "@" + os.path.basename(r.rstrip("\\/")))
        out.append((r, seen[r], bool(outer)))
    return out


def externals(p4):
    """{absolute root outside the project: its path prefix}, for transcript.rel."""
    s = load_state(p4)
    return {r: v["prefix"] for r, v in s.get("roots", {}).items() if v.get("prefix", "").startswith("@")}


# --- packages of a root ----------------------------------------------------------------------------------

def subdirs(d):
    try:
        with os.scandir(d) as it:
            return sorted(e.name for e in it if e.is_dir(follow_symlinks=True))
    except OSError:
        return []


def kind_of(root):
    base = os.path.basename(root.rstrip("\\/"))
    return {"node_modules": "node", "site-packages": "site", "_deps": "fetch"}.get(base, "tree")


def packages(root, prefix, split=False):
    """[{name, dir (absolute, '' when the package is only a record), path (shown), kind, meta}] of one root. A split
    root is its directories, each a package, and itself for the files directly in it (`flat`: read within the caps,
    the rest listed by name), whatever manifest it has."""
    kind = kind_of(root)
    out = []

    def add(name, d, k=kind, meta=""):
        rel = posix(os.path.relpath(d, root)) if d else ""
        out.append({"name": name, "dir": d, "kind": k, "meta": meta,
                    "path": prefix if rel in ("", ".") and d else f"{prefix}/{rel or name}"})

    if kind == "node":
        for n in subdirs(root):
            if n.startswith("."):
                continue
            if n.startswith("@"):
                for m in subdirs(os.path.join(root, n)):
                    if os.path.exists(os.path.join(root, n, m, "package.json")):
                        add(f"{n}/{m}", os.path.join(root, n, m))
            elif os.path.exists(os.path.join(root, n, "package.json")):
                add(n, os.path.join(root, n))
    elif kind == "site":
        for n in subdirs(root):
            m = re.match(r"^(.+?)-(\d[^-]*)\.dist-info$", n)
            if m:
                top = os.path.join(root, m.group(1).replace("-", "_"))
                add(m.group(1), top if os.path.isdir(top) else "", meta=os.path.join(root, n))
    elif kind == "fetch":
        for n in subdirs(root):
            if n.endswith("-src"):
                add(n[:-4], os.path.join(root, n))
    elif split:
        add(os.path.basename(root.rstrip("\\/")), root)
        own = out[-1]
        own["flat"] = True
        for n in subdirs(root):
            if not n.startswith(".") and n.lower() not in SKIP_DIRS:
                add(n, os.path.join(root, n))
        own["inner"] = [p["dir"] for p in out if p is not own]
    elif any(os.path.exists(os.path.join(root, m)) for m in MANIFESTS):
        add(os.path.basename(root.rstrip("\\/")), root)
    else:
        for n in subdirs(root):
            if n.startswith("."):
                continue
            d = os.path.join(root, n)
            if kind_of(d) != "tree":
                out.extend(packages(d, f"{prefix}/{n}"))
            else:
                add(n, d)
    return out


def direct_names(project, root):
    """The package names the project's own manifests ask for (the manifest beside a node_modules; requirements and
    pyproject at the project root): those are read in full. None when no manifest says, so every package is."""
    names = set()
    if kind_of(root) == "node":
        try:
            with open(os.path.join(os.path.dirname(root), "package.json"), encoding="utf-8") as f:
                pj = json.load(f)
            for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                names.update((pj.get(k) or {}).keys())
        except (OSError, ValueError, AttributeError):
            return None
        return names
    if kind_of(root) == "site":
        for fn in ("requirements.txt", "requirements.lock", "pyproject.toml"):
            try:
                with open(os.path.join(project, fn), encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                continue
            for m in re.finditer(r"(?m)^\s*[\"']?([A-Za-z][\w.-]*)\s*(?:[=<>~!\[;\"',]|$)", text):
                names.add(m.group(1).lower().replace("_", "-"))
        return names or None
    return None


# --- version and signature -------------------------------------------------------------------------------

def read_head(path, n=65536):
    try:
        with open(path, "rb") as f:
            return f.read(n).decode("utf-8", "replace")
    except OSError:
        return ""


def git_head(d):
    """The commit a checkout is at (12 characters), read from its .git without running git; '' when there is none."""
    g = os.path.join(d, ".git")
    if os.path.isfile(g):                                   # a worktree's or a submodule's pointer
        m = re.match(r"gitdir:\s*(.+)", read_head(g, 500))
        if not m:
            return ""
        g = m.group(1).strip()
        g = g if os.path.isabs(g) else os.path.normpath(os.path.join(d, g))
    head = read_head(os.path.join(g, "HEAD"), 200).strip()
    if not head:
        return ""
    if not head.startswith("ref:"):
        return head[:12]
    ref = head[4:].strip()
    sha = read_head(os.path.join(g, ref), 100).strip()
    if not sha:
        m = re.search(r"(?m)^([0-9a-f]{40})\s+" + re.escape(ref) + r"\s*$", read_head(os.path.join(g, "packed-refs"),
                                                                                     4 << 20))
        sha = m.group(1) if m else ""
    return sha[:12]


def describe(pkg):
    """(version, description) of a package, from the cheapest sources that say."""
    d, ver, desc = pkg["dir"], "", ""
    if pkg["kind"] == "site":
        m = re.match(r"^.+?-(\d[^-]*)\.dist-info$", os.path.basename(pkg["meta"]))
        ver = m.group(1) if m else ""
        m = re.search(r"(?m)^Summary:\s*(.+)$", read_head(os.path.join(pkg["meta"], "METADATA"), 8192))
        return ver, (m.group(1).strip()[:200] if m else "")
    if not d:
        return "", ""
    text = read_head(os.path.join(d, "package.json"))
    if text:
        try:
            pj = json.loads(text)
            ver, desc = str(pj.get("version") or ""), str(pj.get("description") or "")[:200]
        except (ValueError, AttributeError):
            pass
    if not ver:
        m = re.search(r"(?is)\bproject\s*\(\s*[\w.+-]+[^)]*?\bVERSION\s+([\w.+-]+)", read_head(os.path.join(d, "CMakeLists.txt")))
        ver = m.group(1) if m else ""
    if not ver:
        for fn in ("pyproject.toml", "Cargo.toml", "vcpkg.json"):
            m = re.search(r"(?m)^\s*\"?version(?:-string|-semver)?\"?\s*[=:]\s*\"([^\"]+)\"", read_head(os.path.join(d, fn)))
            if m:
                ver = m.group(1)
                break
    if not ver:
        for fn in ("VERSION", "VERSION.txt", "version.txt"):
            t = " ".join(read_head(os.path.join(d, fn), 400).split())
            if t:
                ver = t[:60]
                break
    head = git_head(d) or git_head(os.path.join(d, "src"))
    if head:
        ver = f"{ver} @{head}".strip()
    if not ver:
        for cand in (d.rstrip("\\/") + ".sha256", os.path.join(d, "binary.sha256")):
            t = read_head(cand, 100).strip()
            if t:
                ver = "sha256:" + t[:12]
                break
        else:
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.name.endswith(".sha256") and e.is_file():
                            ver = "sha256:" + read_head(e.path, 100).strip()[:12]
                            break
            except OSError:
                pass
    return ver, desc


def signature(pkg, version, opened=()):
    """The version and the top-level files' names, sizes and times: it moves when the package is put there again.
    The files a session opened in it are part of it, so a newly opened one has the package read again."""
    asked, rows = sorted("opened:" + f for f in opened) + [f"caps:{FILES}:{ENTRIES}:{DEPTH}:{SCAN}" + (f":flat:{LISTED}" if pkg.get("flat") else "")], []
    for d in (pkg["dir"], pkg["meta"]):
        if not d:
            continue
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_file(follow_symlinks=False):
                            s = e.stat()
                            rows.append(f"{e.name}:{s.st_size}:{s.st_mtime_ns}")
                    except OSError:
                        continue
        except OSError:
            continue
    return sha8(version + "|" + "|".join(asked + sorted(rows)[:SIG_FILES]))     # asked whole: never cut by the files


# --- entries of one package ------------------------------------------------------------------------------

def rank_file(rel, entry_points):
    """Lower is read first: documents and manifests, the entry points a manifest names, then public directories,
    then by depth."""
    parts = rel.split("/")
    base = parts[-1].lower()
    stem = base.rsplit(".", 1)[0]
    if len(parts) == 1 and (stem in DOC_NAMES or base in ("package.json", "cmakelists.txt", "pyproject.toml")):
        return (0, rel)
    if rel in entry_points:
        return (1, rel)
    public = any(p.lower() in PUBLIC_DIRS for p in parts[:-1])
    header = base.endswith((".h", ".hpp", ".hh", ".hxx", ".d.ts", ".pyi"))
    return (2 if public and header else 3 if public or header else 4, len(parts), rel)


def walk(d, flat=False):
    """Relative paths of a package's readable files, breadth first, bounded by SCAN entries and DEPTH levels; `flat`
    is its own directory only."""
    out, level, seen = [], [""], 0
    for _ in range(1 if flat else DEPTH + 1):
        nxt = []
        for sub in level:
            try:
                it = os.scandir(os.path.join(d, sub) if sub else d)
            except OSError:
                continue
            with it:
                for e in sorted(it, key=lambda e: e.name):
                    seen += 1
                    if seen > SCAN:
                        return out
                    rel = f"{sub}/{e.name}" if sub else e.name
                    try:
                        isdir = e.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    low = e.name.lower()
                    if isdir:
                        if not low.startswith(".") and low not in SKIP_DIRS and not low.endswith(("-build", "-tmp", "-subbuild")):
                            nxt.append(rel)
                        continue
                    ext = low.rsplit(".", 1)[-1] if "." in low else ""
                    if ext in repo.BINARY_EXT or ".min." in low or low.startswith("."):
                        continue
                    if ext in repo.LANG or low.endswith(repo.MD_EXT) or low in ("cmakelists.txt", "package.json",
                                                                               "pyproject.toml", "makefile"):
                        out.append(rel)
        level = nxt
    return out


def entry_points(d):
    try:
        pj = json.loads(read_head(os.path.join(d, "package.json")) or "{}")
    except ValueError:
        return set()
    out = set()
    for k in ("main", "module", "types", "typings"):
        if isinstance(pj.get(k), str):
            out.add(posix(os.path.normpath(pj[k])).lstrip("./"))
    return out


def spread(files, eps):
    """The files in reading order: documents, manifests and entry points first; then one from each directory in
    turn (a directory is a path's first two parts), each directory's own files by rank, so a cap leaves out the
    depths of every directory and not the directories late in the alphabet."""
    ranked = sorted(files, key=lambda r: rank_file(r, eps))
    first = [r for r in ranked if rank_file(r, eps)[0] <= 1]
    buckets = {}
    for r in ranked[len(first):]:
        buckets.setdefault("/".join(r.split("/")[:2]) if r.count("/") > 1 else r.split("/")[0], []).append(r)
    rest, queues = [], [buckets[k] for k in sorted(buckets, key=lambda k: rank_file(buckets[k][0], eps))]
    i = 0
    while queues:
        queues = [q for q in queues if i < len(q)]
        rest += [q[i] for q in queues]
        i += 1
    return first + rest


def package_entries(pkg, version, desc, light=False, opened=()):
    """[{id, line, sym, text, path}] of one package: its own entry, the files a session opened in it, then its
    files' in spread()'s order, within the caps."""
    p = pkg["path"]
    out = [{"id": f"repo:{p}", "path": p, "line": 1, "sym": "",
            "text": f"{p} {pkg['name']} {version} {desc} dependency package".strip()}]
    d = pkg["dir"]
    if not d:
        return out
    max_files, max_entries = (LIGHT_FILES, LIGHT_ENTRIES) if light else (FILES, ENTRIES)
    eps = entry_points(d)
    files = spread(walk(d, pkg.get("flat", False)), eps)
    if light:
        files = [r for r in files if rank_file(r, eps)[0] <= 1]
    mine = [r for r in opened if os.path.isfile(os.path.join(d, r.replace("/", os.sep)))]
    read = 0
    for rel in list(dict.fromkeys(mine + files)):
        asked = rel in mine                              # what a session opened is read past the caps
        if not asked and (read >= max_files or len(out) >= max_entries):
            break
        text, why = repo.read_file(d, rel.replace("/", os.sep))
        if why:
            continue
        read += 1
        for e in repo.file_entries(f"{p}/{rel}", text)[:PER_FILE if asked else max(1, min(PER_FILE, max_entries - len(out)))]:
            out.append({"id": e["id"], "path": f"{p}/{rel}", "line": e["line"], "sym": e["sym"], "text": e["text"]})
    if pkg.get("flat"):                                  # the folder the owner named: every file of its own, by name
        have = {e["path"] for e in out}
        for rel in files:
            if len(out) >= LISTED:
                break
            if f"{p}/{rel}" not in have:
                out.append({"id": f"repo:{p}/{rel}", "path": f"{p}/{rel}", "line": 1, "sym": "", "text": f"{p}/{rel}"})
    return out


def note_opened(p4, paths):
    """Remember the dependency files a turn opened that the index does not hold (`paths` in the entries' form, e.g.
    `@framework/include/api.h`): each is filed under the longest package path it sits in, and that package is read
    again at the next build with those files first. Returns how many were new."""
    s = load_state(p4)
    pkgs = sorted(((v["path"], v) for rs in s.get("roots", {}).values() for v in rs["packages"].values()),
                  key=lambda x: len(x[0]), reverse=True)
    new = 0
    for p in paths:
        for path, v in pkgs:
            if p.startswith(path + "/"):
                rel = p[len(path) + 1:]
                if any(e["path"] == p for e in v["entries"]):
                    break
                got = s.setdefault("opened", {}).setdefault(path, [])
                if rel not in got:
                    got.insert(0, rel)
                    del got[OPENED:]
                    new += 1
                break
    if new:
        ranker.write_atomic(state_path(p4), json.dumps(s, separators=(",", ":"), ensure_ascii=False))
    return new


def opened_in_turn(turn, project):
    """The paths (entries' form) of the files a turn's Read and Edit calls name."""
    import transcript as tr
    cwd = turn.get("cwd") or project
    out = []
    for c in turn.get("calls", []):
        inp = c.get("input") if isinstance(c.get("input"), dict) else {}
        if c.get("name") in tr.READ_TOOLS + tr.EDIT_TOOLS:
            r = tr.rel(inp.get("file_path") or inp.get("notebook_path") or "", project, cwd)
            if r:
                out.append(r)
    return out


# --- what the project itself uses ------------------------------------------------------------------------

def project_includes(project, named=()):
    """The paths the project's own sources include or import (`#include "a/b.h"`, `import "a/b.mojom";`), most
    included first. Its own are the files git tracks outside the roots the settings name (`named`, absolute): a
    patch the project keeps over a vendored tree is its own, a package checked in whole under a named root is not.
    [] when it is not a repository."""
    try:
        if not repo.is_repo(project):
            return []
        paths = sorted(repo.tracked(project))
    except (OSError, RuntimeError):
        return []
    proj = os.path.normpath(project) + os.sep
    inside = [posix(r[len(proj):]) + "/" for r in named if r.startswith(proj)]
    count = {}
    for path in paths:
        if not path.lower().endswith(SOURCE_EXT) or any(path.startswith(i) for i in inside):
            continue
        try:
            with open(os.path.join(project, path), encoding="utf-8", errors="replace") as f:
                text = f.read(SOURCE_BYTES)
        except OSError:
            continue
        for m in INCLUDE.finditer(text):
            inc = posix(m.group(1) or m.group(2)).lstrip("/")
            if "/" in inc and ".." not in inc:
                count[inc] = count.get(inc, 0) + 1
    return sorted(count, key=lambda k: (-count[k], k))


def used_in(pkg, includes, others=()):
    """The files of one package the project includes, as paths in the package, most included first. An include is
    relative to the package, to its src/, or to a directory above it (`media/audio/x.h` names a file of the package
    at .../src/media/audio); a file under one of `others` (a root or package inside this one) is theirs."""
    d = pkg["dir"]
    if not d or not includes:
        return []
    leads, a, lead = [], d, ""
    for _ in range(UP):
        parent = os.path.dirname(a)
        if parent == a:
            break
        lead = os.path.basename(a) + ("/" + lead if lead else "")
        leads.append(lead + "/")
        a = parent
    tops, src = set(subdirs(d)), set(subdirs(os.path.join(d, "src")))
    skip = [os.path.normpath(o) + os.sep for o in list(others) + pkg.get("inner", [])]
    out = []
    for inc in includes:
        first = inc.split("/", 1)[0]
        cands = [inc[len(l):] for l in leads if inc.startswith(l)]
        cands += [inc] if first in tops else []
        cands += ["src/" + inc] if first in src else []
        for rel in cands:
            full = os.path.normpath(os.path.join(d, rel))
            if not any(full.startswith(s) for s in skip) and os.path.isfile(full):
                out.append(rel)
                break
        if len(out) >= USED:
            break
    return out


# --- the incremental build -------------------------------------------------------------------------------

def state_path(p4):
    return os.path.join(p4, "models", STATE)


def load_state(p4):
    try:
        with open(state_path(p4), encoding="utf-8") as f:
            s = json.load(f)
        if s.get("version") == VERSION:
            return s
    except (OSError, ValueError):
        pass
    return {"version": VERSION, "project": "", "roots": {}, "updates": [], "changed_at": 0, "entries": 0, "cut": 0}


def build(p4, project=None, deadline_s=None, now=None, now_s=None):
    """Bring models/deps.json up to date with the dependency roots. Returns stats: {roots, packages, read (packages
    read again), installed, updated, removed, entries, cut, complete}. The file is written only when something
    moved, so an unchanged tree never makes the index stale."""
    project = os.path.abspath(project or repo.project_of(p4) or "")
    if not project or not os.path.isdir(project):
        raise RuntimeError(f"no project directory: {project or '(none)'}")
    t0 = time.time()
    now = now or time.strftime("%Y-%m-%d %H:%M")
    s = load_state(p4)
    if s.get("project") and s["project"] != project:
        s = load_state(os.path.join(p4, "no-such"))
    s["project"] = project
    stats = {"roots": 0, "packages": 0, "read": 0, "installed": 0, "updated": 0, "removed": 0, "complete": True}
    moved = False
    live = roots(project)
    for r in [r for r in s["roots"] if r not in {x[0] for x in live}]:
        stats["removed"] += len(s["roots"][r]["packages"])
        del s["roots"][r]
        moved = True
    includes = project_includes(project, [os.path.normpath(os.path.join(project, os.path.expanduser(str(r)))) for r in ROOTS])
    for root, prefix, split in live:
        stats["roots"] += 1
        first = root not in s["roots"]
        rs = s["roots"].setdefault(root, {"prefix": prefix, "packages": {}})
        rs["prefix"] = prefix
        pkgs = packages(root, prefix, split)
        direct = direct_names(project, root)
        names = {p["name"] for p in pkgs}
        for gone in [n for n in rs["packages"] if n not in names]:
            old = rs["packages"].pop(gone)
            s["updates"].insert(0, [now, gone, old.get("version", ""), "", old.get("path", ""), "removed"])
            stats["removed"] += 1
            moved = True
        for pkg in pkgs:
            stats["packages"] += 1
            if deadline_s is not None and time.time() - t0 > deadline_s:
                stats["complete"] = False
                continue
            version, desc = describe(pkg)
            nested = [r for r, _p, _s in live if pkg["dir"] and r != root and
                      (r + os.sep).startswith(os.path.normpath(pkg["dir"]) + os.sep)]
            opened = list(dict.fromkeys(s.get("opened", {}).get(pkg["path"], []) + used_in(pkg, includes, nested)))
            sig = signature(pkg, version, opened)
            old = rs["packages"].get(pkg["name"])
            if old and old.get("sig") == sig:
                continue
            light = pkg.get("light", False) or direct is not None and pkg["name"].lower().replace("_", "-") not in {n.lower() for n in direct}
            rs["packages"][pkg["name"]] = {"sig": sig, "version": version, "path": pkg["path"], "at": now,
                                           "light": light,
                                           "entries": package_entries(pkg, version, desc, light, opened)}
            stats["read"] += 1
            moved = True
            if old and old.get("version") != version:
                s["updates"].insert(0, [now, pkg["name"], old.get("version", ""), version, pkg["path"], "updated"])
                stats["updated"] += 1
            elif not old and not first:
                s["updates"].insert(0, [now, pkg["name"], "", version, pkg["path"], "installed"])
                stats["installed"] += 1
            elif not old:
                stats["installed"] += 1
    s["updates"] = s["updates"][:MAX_UPDATES]
    # the cap: the most recently read packages first; a package that would pass it is left out whole
    order = sorted(((v["at"], r, n) for r, rs in s["roots"].items() for n, v in rs["packages"].items()), reverse=True)
    n, cut = 0, 0
    for _at, r, name in order:
        v = s["roots"][r]["packages"][name]
        k = len(v["entries"])
        if n + k > MAX_ENTRIES:
            moved = moved or not v.get("cut")
            v["cut"] = True
            cut += 1
            continue
        moved = moved or bool(v.pop("cut", None))
        n += k
    stats.update({"entries": n, "cut": cut})
    if moved or not os.path.exists(state_path(p4)):
        if stats["read"] or stats["removed"]:
            s["changed_at"] = now_s or time.time()
        s.update({"entries": n, "cut": cut, "built": now})
        os.makedirs(os.path.dirname(state_path(p4)), exist_ok=True)
        ranker.write_atomic(state_path(p4), json.dumps(s, separators=(",", ":"), ensure_ascii=False))
    return stats


def entries(p4):
    """The docs the index adds for the dependencies, in repo.entries' form: file entries, then the updates."""
    s = load_state(p4)
    out, known, seen = [], set(), set()
    for r in sorted(s.get("roots", {})):
        for name in sorted(s["roots"][r]["packages"]):
            v = s["roots"][r]["packages"][name]
            if v.get("cut"):
                continue
            known.add(v["path"])
            for e in v["entries"]:
                if e["id"] in seen:                      # a root named inside another: the same file from both
                    continue
                seen.add(e["id"])
                pkg = e["id"] == f"repo:{v['path']}"
                show = (f"{e['path']} ({name} {v.get('version', '')}".rstrip() + ", a dependency)" if pkg
                        else f"{e['path']} — {e['sym']}" if e["sym"] else e["path"])
                out.append({"id": e["id"], "path": e["path"], "line": e["line"], "kind": "file", "time": v["at"][:10],
                            "show": show, "text": e["text"], "head": show})
    for when, name, old, new, path, what in s.get("updates", []):
        if what == "removed":
            head = f"{name} {old} removed".replace("  ", " ")
        elif what == "installed":
            head = f"{name} {new} installed".replace("  ", " ")
        else:
            head = f"{name} updated {old or '(unknown)'} -> {new or '(unknown)'}"
        out.append({"id": f"dep-update:{sha8(f'{when}|{name}|{old}|{new}')}", "path": f"dependency {name}", "line": 0,
                    "kind": "commit", "time": when[:10], "show": f"{head} ({path})", "text": f"{head} {path} dependency",
                    "head": head, "paths": [path] if path in known else []})
    return out


def changed_at(p4):
    """When a package was last installed, updated or removed (epoch seconds); 0 when never."""
    return float(load_state(p4).get("changed_at") or 0)


def stats_line(p4):
    s = load_state(p4)
    if not s.get("roots"):
        return ""
    n = sum(len(r["packages"]) for r in s["roots"].values())
    light = sum(1 for r in s["roots"].values() for v in r["packages"].values() if v.get("light"))
    return (f"deps: {n} packages in {len(s['roots'])} roots ({light} transitive, read lightly), {s.get('entries', 0)} "
            f"entries, {len(s.get('updates', []))} updates recorded"
            + (f"; cut at {MAX_ENTRIES} entries: {s['cut']} packages left out (oldest-read)" if s.get("cut") else ""))
