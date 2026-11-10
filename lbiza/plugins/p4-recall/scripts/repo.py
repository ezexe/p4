#!/usr/bin/env python3
"""repo.py: the repository itself as recall entries (fresh-marketplace.md 4.1a), `p4.py index --repo`.

Indexed mechanically from `git ls-files -s` and `git log`, incrementally: a file is re-read only when its blob sha
changed since the last run, and the history reads only `git log <last indexed commit>..HEAD`, so a rebuild after
one commit touches that commit's files alone. The state lives in `models/repo.json` (a cache, ignored by git); the
entries join `models/index.json` at the next index build.

Entries:
  path      every tracked file's path                                  id repo:<path>
  heading   each Markdown heading: path, heading, the first line under it   id repo:<path>#<sha8 heading>
  symbol    top-level definitions and classes by a cheap regex per language, as `path:line symbol`
  target    build targets and scripts (CMakeLists.txt, *.cmake, Makefile, package.json scripts, pyproject.toml)
  commit    `<date> <sha8> <subject>; touched: <paths>`, newest first, the last MAX_COMMITS   id commit:<sha8>
Conventions (CLAUDE.md, CLAUDE.local.md, AGENTS.md, README*, CONTRIBUTING*, .github/*.md) are Markdown and indexed
by section like any other.

Excluded: anything ignored (ls-files lists tracked files only; a tracked file the ignore rules match is dropped too),
LFS pointers, binaries (BINARY_EXT and a NUL in the first 8 KB), vendored and generated code (node_modules/,
third_party/, vendor/, *.min.*, *.generated.*, a first line that says `generated`, any directory a `.p4ignore`
names), and files over 512 KB. File entries stop at MAX_FILE_ENTRIES (50,000), newest-touched files first; `check`
reports the cut.
"""

import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ranker  # noqa: E402

STATE = "repo.json"
VERSION = 1
MAX_BYTES = 512 * 1024
MAX_FILE_ENTRIES = 50000
MAX_COMMITS = 2000
MAX_TOUCHED = 12               # paths listed on one commit entry
VENDORED_DIRS = ("node_modules", "third_party", "vendor")
BINARY_EXT = frozenset("""png jpg jpeg gif bmp ico icns webp tif tiff psd svgz pdf zip gz tgz bz2 xz 7z rar tar jar war
dmg iso exe dll so dylib a lib o obj class pyc pyo whl egg wasm bin dat db sqlite sqlite3 mp3 mp4 m4a wav flac ogg
aac mov avi mkv webm ttf otf woff woff2 eot pt pth onnx npy npz pkl h5 ckpt safetensors phid lfs""".split())
MD_EXT = (".md", ".markdown", ".mdx")
LFS_HEAD = b"version https://git-lfs.github.com/spec/"

SYMBOL_RES = {
    "py": [re.compile(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)"), re.compile(r"^class\s+([A-Za-z_]\w*)")],
    "js": [re.compile(r"^(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)"),
           re.compile(r"^(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"),
           re.compile(r"^export\s+(?:const|let|var|type|interface|enum)\s+([A-Za-z_$][\w$]*)")],
    "rs": [re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)"),
           re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)"),
           re.compile(r"^impl(?:<[^>]*>)?\s+(?:[\w:<>, ]+\s+for\s+)?([A-Za-z_][\w:]*)")],
    "c": [re.compile(r"^(?:class|struct|union|enum(?:\s+class)?)\s+(?:\w+\s+)*?([A-Za-z_]\w*)\s*(?:final\s*)?[:{]"),
          re.compile(r"^(?:namespace)\s+([A-Za-z_][\w:]*)"),
          re.compile(r"^(?:template\s*<[^>]*>\s*)?(?:(?:static|inline|virtual|extern|constexpr|explicit|unsigned|"
                     r"signed|const|struct)\s+)*[A-Za-z_][\w:<>,*&\s]*?[\s*&]([A-Za-z_][\w:~]*)\s*\([^;]*$")],
    "java": [re.compile(r"^(?:public\s+|private\s+|protected\s+)?(?:abstract\s+|final\s+|static\s+)*"
                        r"(?:class|interface|enum|record|struct)\s+([A-Za-z_]\w*)"),
             re.compile(r"^\s{0,4}(?:public|private|protected|internal|static|override|async|func)\s+[\w<>\[\], ]*?"
                        r"([A-Za-z_]\w*)\s*\(")],
    "swift": [re.compile(r"^(?:public\s+|private\s+|internal\s+|open\s+|final\s+)*(?:class|struct|enum|protocol|"
                         r"extension|actor)\s+([A-Za-z_]\w*)"),
              re.compile(r"^(?:public\s+|private\s+|internal\s+|open\s+|static\s+)*func\s+([A-Za-z_]\w*)")],
    "go": [re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"), re.compile(r"^type\s+([A-Za-z_]\w*)")],
    "sh": [re.compile(r"^(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{?"), re.compile(r"^function\s+([A-Za-z_][\w-]*)")],
}
LANG = {"py": "py", "js": "js", "jsx": "js", "ts": "js", "tsx": "js", "mjs": "js", "cjs": "js", "rs": "rs",
        "c": "c", "h": "c", "cc": "c", "cpp": "c", "cxx": "c", "hh": "c", "hpp": "c", "hxx": "c", "m": "c", "mm": "c",
        "java": "java", "cs": "java", "kt": "java", "swift": "swift", "go": "go", "sh": "sh", "bash": "sh",
        "zsh": "sh"}
C_SKIP = frozenset(("if", "for", "while", "switch", "return", "else", "sizeof", "do", "case", "catch", "using",
                    "typedef", "define", "include", "defined"))
CMAKE_TARGET = re.compile(r"^\s*(?:add_executable|add_library|add_custom_target|add_test|function|macro)\s*\(\s*"
                          r"(?:NAME\s+)?([A-Za-z_][\w.+-]*)", re.I)
MAKE_TARGET = re.compile(r"^([A-Za-z_][\w.-]*)\s*:(?!=)")


# --- git -------------------------------------------------------------------------------------------------

def git(project, *args, timeout=60):
    r = subprocess.run(["git", "-C", project] + list(args), capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {r.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return r.stdout.decode("utf-8", "replace")


def is_repo(project):
    try:
        return git(project, "rev-parse", "--is-inside-work-tree", timeout=10).strip() == "true"
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return False


def tracked(project):
    """{path: blob sha} of the tracked files, the ones the ignore rules match dropped."""
    out = {}
    for l in git(project, "ls-files", "-s", "-z").split("\0"):
        if not l:
            continue
        meta, _, path = l.partition("\t")
        parts = meta.split()
        if len(parts) >= 2 and parts[0] != "160000":          # a submodule is not a file
            out[path] = parts[1]
    try:
        ign = git(project, "ls-files", "-z", "-i", "-c", "--exclude-standard").split("\0")
        for p in ign:
            out.pop(p, None)
    except RuntimeError:
        pass
    return out


def head(project):
    try:
        return git(project, "rev-parse", "HEAD", timeout=10).strip()
    except RuntimeError:
        return ""


def commits(project, since="", limit=MAX_COMMITS):
    """[(sha, date, subject, [paths])], newest first: `git log <since>..HEAD`, or the last `limit` commits."""
    rng = [f"{since}..HEAD"] if since else ["HEAD"]
    try:
        text = git(project, "log", *rng, f"-n{limit}", "--no-merges", "--name-only", "--format=\x1e%H\x1f%cs\x1f%s",
                   timeout=120)
    except RuntimeError:
        if since:
            return commits(project, "", limit)     # a rewritten history: read the last `limit` again
        return []
    out = []
    for block in text.split("\x1e"):
        if not block.strip():
            continue
        first, _, rest = block.partition("\n")
        sha, date, subject = (first.split("\x1f") + ["", ""])[:3]
        out.append((sha, date, subject, [p for p in rest.splitlines() if p.strip()]))
    return out


def renames(project, since=""):
    """{old path: the path it has now} for every rename git detects in `since..HEAD` (the whole history when
    `since` is empty). A file renamed twice maps straight to its last name."""
    rng = [f"{since}..HEAD"] if since else ["HEAD"]
    text = git(project, "log", *rng, "-M", "--diff-filter=R", "--name-status", "--format=", "-z", timeout=120)
    toks = [t.strip(chr(10)) for t in text.split(chr(0))]
    out, i = {}, 0
    while i + 2 < len(toks):                     # newest first: a later rename of the new name is already known
        if len(toks[i]) > 1 and toks[i][0] == "R" and toks[i][1:].isdigit():
            old, new = toks[i + 1], toks[i + 2]
            out[old] = out.get(new, new)
            i += 3
        else:
            i += 1
    return out


def merge_renames(known, newer):
    """The map after more history: what was known, moved along by the newer renames, and the newer ones."""
    out = {old: newer.get(now, now) for old, now in known.items()}
    for old, now in newer.items():
        out.setdefault(old, now)
    return {old: now for old, now in out.items() if old != now}


# --- exclusions ------------------------------------------------------------------------------------------

def p4ignore(project):
    """Directories a `.p4ignore` at the project root names, one per line (# comments)."""
    path = os.path.join(project, ".p4ignore")
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for l in f:
                l = l.split("#", 1)[0].strip().strip("/")
                if l:
                    out.append(l)
    except OSError:
        pass
    return out


def excluded_by_path(path, ignored_dirs=()):
    """The reason a path is out before it is opened, or ''."""
    parts = path.split("/")
    if any(p in VENDORED_DIRS for p in parts[:-1]):
        return "vendored"
    base = parts[-1].lower()
    if ".min." in base or ".generated." in base or base.endswith((".min", ".generated")):
        return "generated"
    ext = base.rsplit(".", 1)[-1] if "." in base else ""
    if ext in BINARY_EXT:
        return "binary"
    for d in ignored_dirs:
        if path == d or path.startswith(d + "/"):
            return "p4ignore"
    return ""


def read_file(project, path):
    """(text, reason): the file's text, or '' and why it is out."""
    full = os.path.join(project, path)
    try:
        size = os.path.getsize(full)
    except OSError:
        return "", "missing"
    if size > MAX_BYTES:
        return "", "over 512 KB"
    try:
        with open(full, "rb") as f:
            data = f.read()
    except OSError:
        return "", "unreadable"
    if data.startswith(LFS_HEAD):
        return "", "lfs pointer"
    if b"\0" in data[:8192]:
        return "", "binary"
    text = data.decode("utf-8", "replace")
    first = text.split("\n", 1)[0].lower()
    if re.search(r"\bgenerated\b", first) or "@generated" in text[:400]:
        return "", "generated"
    return text, ""


# --- entries of one file ---------------------------------------------------------------------------------

def sha8(s):
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def file_entries(path, text):
    """[{id, kind, line, text, sym}] for one file: its path, then its headings, symbols or targets."""
    out = [{"id": f"repo:{path}", "kind": "file", "line": 1, "sym": "", "text": path}]
    base = path.rsplit("/", 1)[-1]
    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
    lines = text.split("\n")
    seen = set()

    def add(line, sym, extra=""):
        key = sym
        if key in seen:
            return
        seen.add(key)
        out.append({"id": f"repo:{path}#{sha8(sym)}", "kind": "file", "line": line, "sym": sym,
                    "text": f"{path} {sym} {extra}".strip()})

    if path.lower().endswith(MD_EXT):
        in_fence = False
        for i, l in enumerate(lines):
            if l.lstrip().startswith(("```", "~~~")):
                in_fence = not in_fence
            if in_fence:
                continue
            m = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", l)
            if m:
                under = ""
                for x in lines[i + 1:i + 6]:
                    if x.strip() and not x.startswith("#"):
                        under = x.strip()[:200]
                        break
                add(i + 1, m.group(1)[:160], under)
        return out
    if base == "CMakeLists.txt" or ext == "cmake":
        for i, l in enumerate(lines):
            m = CMAKE_TARGET.match(l)
            if m:
                add(i + 1, m.group(1))
        return out
    if base in ("Makefile", "makefile", "GNUmakefile") or ext == "mk":
        for i, l in enumerate(lines):
            m = MAKE_TARGET.match(l)
            if m and not m.group(1).startswith("."):
                add(i + 1, m.group(1))
        return out
    if base == "package.json":
        try:
            scripts = json.loads(text).get("scripts") or {}
        except (ValueError, AttributeError):
            scripts = {}
        for name in scripts:
            ln = next((i + 1 for i, l in enumerate(lines) if f'"{name}"' in l), 1)
            add(ln, f"script {name}")
        return out
    if base == "pyproject.toml":
        sec = ""
        for i, l in enumerate(lines):
            m = re.match(r"^\[(.+)\]\s*$", l)
            if m:
                sec = m.group(1)
                continue
            m = re.match(r"^([A-Za-z_][\w.-]*)\s*=", l)
            if m and sec in ("project.scripts", "tool.poetry.scripts", "project.gui-scripts"):
                add(i + 1, f"script {m.group(1)}")
        return out
    lang = LANG.get(ext)
    if not lang and lines and lines[0].startswith("#!") and re.search(r"\b(ba|z)?sh\b", lines[0]):
        lang = "sh"
    if not lang and lines and lines[0].startswith("#!") and "python" in lines[0]:
        lang = "py"
    if not lang:
        return out
    regs = SYMBOL_RES[lang]
    for i, l in enumerate(lines[:20000]):
        if not l.strip() or l.lstrip()[:1] in "#/*}":
            continue
        indent = len(l) - len(l.lstrip())
        if indent and not (lang in ("java", "swift") and indent <= 4):   # top level; members of a class one level in
            continue
        s_ = l.lstrip()
        for rx in regs:
            m = rx.match(s_)
            if m:
                sym = m.group(1)
                if lang == "c" and (sym in C_SKIP or sym.isupper()):
                    continue
                add(i + 1, sym)
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
    return {"version": VERSION, "project": "", "head": "", "files": {}, "commits": [], "excluded": {}, "cut": 0}


def project_of(p4):
    """The project a .claude/p4 directory belongs to: two levels up."""
    p4 = os.path.abspath(p4)
    if os.path.basename(p4) == "p4" and os.path.basename(os.path.dirname(p4)) == ".claude":
        return os.path.dirname(os.path.dirname(p4))
    return ""


def build(p4, project=None, deadline_s=None, now=None):
    """Bring models/repo.json up to date with the project's git tree. Returns stats:
    {changed, removed, reread, files, entries, commits, new_commits, excluded{reason: n}, cut, complete}."""
    project = os.path.abspath(project or project_of(p4) or "")
    if not project or not is_repo(project):
        raise RuntimeError(f"not a git work tree: {project or '(none)'}")
    t0 = time.time()
    s = load_state(p4)
    if s.get("project") and s["project"] != project:
        s = load_state("/nonexistent")
    s["project"] = project
    files = tracked(project)
    hd = head(project)
    ignored_dirs = p4ignore(project)
    # history first: it also orders the files by when they were last touched
    new = commits(project, s["head"] if s.get("head") and s.get("commits") else "")
    known = {c[0] for c in s["commits"]}
    fresh = [c for c in new if c[0] not in known]
    s["commits"] = (fresh + s["commits"])[:MAX_COMMITS]
    # the renames, so a label on a file's old path still reaches it (labels.follow): the history once, then only
    # what is new since the head they were read at
    if s.get("renames_head") != hd:
        try:
            try:
                got = renames(project, s.get("renames_head", "") if "renames" in s else "")
                s["renames"] = merge_renames(s.get("renames", {}), got)
            except RuntimeError:                   # a rewritten history: read it whole again
                s["renames"] = renames(project)
            s["renames_head"] = hd
        except (RuntimeError, OSError, subprocess.SubprocessError):
            pass
    touched = {}
    for sha, date, subject, paths in reversed(s["commits"]):
        for p in paths:
            touched[p] = date
    old = s["files"]
    removed = [p for p in old if p not in files]
    for p in removed:
        del old[p]
    stats = {"changed": 0, "removed": len(removed), "reread": 0, "excluded": {}, "complete": True,
             "new_commits": len(fresh)}
    for p, sha in files.items():
        rec = old.get(p)
        if rec and rec.get("sha") == sha:
            continue
        if deadline_s is not None and time.time() - t0 > deadline_s:
            stats["complete"] = False
            break
        stats["changed"] += 1
        why = excluded_by_path(p, ignored_dirs)
        text = ""
        if not why:
            text, why = read_file(project, p)
        if why:
            old[p] = {"sha": sha, "out": why}
            continue
        stats["reread"] += 1
        old[p] = {"sha": sha, "entries": file_entries(p, text)}
    excluded = {}
    for p, rec in old.items():
        if rec.get("out"):
            excluded[rec["out"]] = excluded.get(rec["out"], 0) + 1
    s["excluded"] = excluded
    stats["excluded"] = excluded
    s["head"] = hd if stats["complete"] else s.get("head", "")
    s["touched"] = touched
    # the cap: newest-touched files first; a file whose entries would pass the cap is left out whole
    order = sorted((p for p in old if not old[p].get("out")), key=lambda p: (touched.get(p, ""), p), reverse=True)
    n, cut = 0, 0
    for p in order:
        k = len(old[p].get("entries", []))
        if n + k > MAX_FILE_ENTRIES:
            old[p]["cut"] = True
            cut += 1
            continue
        old[p].pop("cut", None)
        n += k
    s["cut"] = cut
    s["entries"] = n
    s["built"] = now or time.strftime("%Y-%m-%d %H:%M")
    ranker.write_atomic(state_path(p4), json.dumps(s, separators=(",", ":"), ensure_ascii=False))
    stats.update({"files": len(order) - cut, "entries": n, "commits": len(s["commits"]), "cut": cut})
    return stats


def entries(p4):
    """The docs the index adds for the repository: (file entries, commit entries) as dicts with id, path, line,
    kind, time, show and the text to tokenize. [] when no repo.json exists."""
    s = load_state(p4)
    if not s.get("files"):
        return []
    touched = s.get("touched", {})
    out = []
    for p in sorted(s["files"]):
        rec = s["files"][p]
        if rec.get("out") or rec.get("cut"):
            continue
        for e in rec.get("entries", []):
            show = f"{p} — {e['sym']}" if e["sym"] else p
            out.append({"id": e["id"], "path": p, "line": e["line"], "kind": "file", "time": touched.get(p, ""),
                        "show": show, "text": e["text"], "head": show})
    for sha, date, subject, paths in s.get("commits", []):
        kept = [p for p in paths if p in s["files"] and not s["files"][p].get("out")]
        shown = kept[:MAX_TOUCHED]                 # an excluded file is never named, here either
        more = len(kept) - len(shown)
        out.append({"id": f"commit:{sha[:8]}", "path": f"commit {sha[:8]}", "line": 0, "kind": "commit",
                    "time": date, "show": f"{subject} ({', '.join(shown)}{f', +{more} more' if more > 0 else ''})",
                    "text": f"{subject} {' '.join(kept)}", "head": subject, "paths": kept})
    return out


def rename_map(p4):
    """{old path: current path} as the last build read it; {} before one has."""
    return load_state(p4).get("renames", {})


def stats_line(p4):
    s = load_state(p4)
    if not s.get("files"):
        return ""
    kept = sum(1 for r in s["files"].values() if not r.get("out") and not r.get("cut"))
    return (f"repo: {kept} files, {s.get('entries', 0)} file entries, {len(s.get('commits', []))} commits; excluded "
            + ", ".join(f"{k} {v}" for k, v in sorted(s.get("excluded", {}).items()))
            + (f"; cut at {MAX_FILE_ENTRIES} file entries: {s['cut']} files left out (oldest-touched)"
               if s.get("cut") else "") + f"; {len(s.get('renames', {}))} renamed paths followed")
