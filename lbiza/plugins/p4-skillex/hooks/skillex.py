#!/usr/bin/env python3
"""skillex.py: p4-skillex, a watcher of temportal that writes the skills brewing there into the store.

A skill is brewing when a project's sessions keep writing the same script in their scratch. The watcher looks at each
script created inside `<project>/.claude/p4/temportal/`, in a session's `tmp/<session>/` or in the notebook
`scratchpad/`, and compares it with the scripts the other sessions wrote there. When scripts of at least
MIN_SESSIONS sessions share at least SIMILAR of their identifiers, the work is brewing, and the watcher writes it as
`<project>/.claude/p4/skillex/<skill_name>/SKILL.md` with the newest script beside it in `scripts/`.

What is compared, measured on the store's 32 session folders:
  kinds      scripts only: SCRIPT_EXT. Markdown that recurs is a brief handed from one session to the next.
  place      a file in the session folder or one folder below it, outside any tree that holds a `.git` or a
             project's root files, SNAPSHOT_MARKS, since a checkout or an export of a repository is a copy.
  measure    the Jaccard index of the two files' identifier sets, identifiers of three or more characters.

Only once a skill exists does the watcher search for something similar that already exists: the skills of this
machine's personal folder, of the plugins and marketplaces Claude Code keeps, of the project, and the store's other
skills. Each match is linked from the new skill's `SKILL.md` under "Similar existing skills" and in `similar.json`.

A store skill reaches every session of the project through Claude Code's own project skills folder: each store skill
is copied into `<project>/.claude/skills/<skill_name>/` with a `.skillex` file naming its source, a SessionStart hook
that changes a copy asks Claude Code to scan the skill folders again with `reloadSkills`, and a copy written during
a session is picked up by Claude Code's watch of that folder. The store keeps the skill; the copy is regenerated
from it and never edited by hand. A folder in `.claude/skills/` without a `.skillex` file is never touched.

  start                        SessionStart: make the store folder and `.claude/skills/`, copy every store skill
                               there.
  write                        PostToolUse on Write: look at the written file when it lies in temportal.
  stop                         Stop: look at the session folder's scripts changed since the last look, so a script
                               written by a shell command is seen too.
  scan [--p4 <store>]          print what is brewing in a store now, writing nothing.
  brew <file> [--p4 <store>]   look at one file by hand, as the write hook does.

Every failure in a hook prints a one-line notice and exits 0.
"""

import json
import math
import os
import re
import shutil
import sys
import time

MIN_SESSIONS = 3                      # sessions whose scripts must share the work, the written one included
SIMILAR = 0.5                         # Jaccard index of identifier sets at and above which two scripts match
MIN_IDENTIFIERS = 15                  # a script with fewer distinct identifiers is too small to compare
MAX_BYTES = 65536                     # a larger file is data or a copy, never compared
MAX_DEPTH = 2                         # the session folder and one folder below it
SCRIPT_EXT = (".py", ".sh", ".ps1", ".js", ".mjs", ".cjs", ".ts", ".bat", ".cmd")
SNAPSHOT_MARKS = (".git", "README.md", "LICENSE", "pyproject.toml", "setup.py", "package.json", ".claude-plugin")
SKIP_DIRS = {"node_modules", "__pycache__", ".pytest_cache", "venv", ".venv", ".out"}
SEARCH_DEADLINE_S = 3.0
SEARCH_MAX_FILES = 5000
SEARCH_KEEP = 3
SEARCH_MIN_SCORE = 0.18                # measured: the true matches scored 0.195 to 0.198, the best false one 0.143
MARKER = ".skillex"                   # in a copy under .claude/skills/: the store folder it was copied from
COPY_IGNORE = ".gitignore"            # in a copy under .claude/skills/: `*`, so git never tracks the copy
# What a secret looks like in a script: a private key, a known token's shape, or a quoted value given to a name that
# says key, token, secret or password. A script that holds one brews no skill, so it is never copied anywhere.
SECRETS = [re.compile(p) for p in (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|glpat-[A-Za-z0-9_-]{20,})",
    r"(?i)\b[\w-]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)[\w-]*\b[\"']?\s*[:=]\s*"
    r"[\"'][^\"'\s]{8,}[\"']",
)]
STATE = ".state"                      # in the store folder: the index of compared scripts and each session's last look
NOTEBOOK = "scratchpad"               # temportal's notebook, compared as one more session
BREWED = " Brewed by p4-skillex from scripts written in "   # how a written skill's description ends

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
WORD = re.compile(r"[a-z]{3,}")
STOP_WORDS = set("""
this that with from into when then than what which where while have been were will would should could their there
these those them they your over only also each such more most other some used uses using file files line lines path
paths name names make made does done true false none self args return import print main pass else elif break
continue class with open read write test tests python script scripts skill skills claude code session sessions
the and for its are not but use all any can one two out set get new run via per how may has was who why see own
""".split())


# ---------------------------------------------------------------------------------------------------------------- paths

def payload_from_stdin():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def project_root(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def store_of(root):
    return os.path.join(root, ".claude", "p4")


def skillex_dir(p4):
    return os.path.join(p4, "skillex")


def project_skills(p4):
    """The project's own skills folder beside the store: `<project>/.claude/skills`."""
    return os.path.join(os.path.dirname(os.path.abspath(p4)), "skills")


def real(p):
    """The path with every link resolved, as the file system spells it."""
    try:
        return os.path.realpath(p)
    except OSError:
        return os.path.abspath(p)


def key(p):
    """real(p) in the form two paths are compared in."""
    return os.path.normcase(real(p))


def where_in_temportal(p4, path):
    """For a file inside temportal: its session and the folder that session's scripts live in, else None.

    A file in `tmp/<session>/` belongs to that session, and one in the notebook `scratchpad/` to the pseudo-session
    NOTEBOOK. The path is resolved first, since a session scratchpad is a link into `tmp/<session>/`."""
    t = real(os.path.join(p4, "temportal"))
    f = real(path)
    if not os.path.normcase(f).startswith(os.path.normcase(t) + os.sep):
        return None
    parts = f[len(t) + 1:].split(os.sep)
    if len(parts) >= 3 and parts[0] == "tmp":
        return parts[1], os.path.join(t, "tmp", parts[1])
    if len(parts) >= 2 and parts[0] == NOTEBOOK:
        return NOTEBOOK, os.path.join(t, NOTEBOOK)
    return None


def comparable(base, path):
    """True for a script at most MAX_DEPTH deep under `base`, resolving inside it, and outside any snapshot of a
    repository. The session folder's own top level is never a snapshot, whatever files it holds."""
    if not path.lower().endswith(SCRIPT_EXT):
        return False
    try:
        rel = os.path.relpath(real(path), real(base))
    except ValueError:                                   # resolves to another drive
        return False
    parts = rel.split(os.sep)
    if len(parts) > MAX_DEPTH or any(p in SKIP_DIRS or p == ".." for p in parts[:-1]) or parts[0] == "..":
        return False
    d = os.path.dirname(os.path.join(real(base), rel))
    while key(d) != key(base):
        if any(os.path.exists(os.path.join(d, m)) for m in SNAPSHOT_MARKS):
            return False
        d = os.path.dirname(d)
    return True


def scripts_of(base):
    """Every comparable script under one session folder."""
    out = []
    for r, ds, fs in os.walk(base):
        depth = 0 if r == base else os.path.relpath(r, base).count(os.sep) + 1
        if r != base and any(os.path.exists(os.path.join(r, m)) for m in SNAPSHOT_MARKS):
            ds[:] = []
            continue
        ds[:] = [d for d in ds if d not in SKIP_DIRS and depth + 1 < MAX_DEPTH]
        for f in fs:
            p = os.path.join(r, f)
            if f.lower().endswith(SCRIPT_EXT) and comparable(base, p):
                out.append(p)
    return out


def sessions_of(p4):
    """Each session folder in temportal's tmp, and the notebook, as a session and its folder."""
    t = os.path.join(p4, "temportal")
    out = []
    tmp = os.path.join(t, "tmp")
    if os.path.isdir(tmp):
        for s in sorted(os.listdir(tmp)):
            d = os.path.join(tmp, s)
            if os.path.isdir(d):
                out.append((s, d))
    if os.path.isdir(os.path.join(t, NOTEBOOK)):
        out.append((NOTEBOOK, os.path.join(t, NOTEBOOK)))
    return out


# -------------------------------------------------------------------------------------------------------- comparing

def identifiers(path):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            ids = set(IDENT.findall(f.read()))
    except OSError:
        return None
    return ids if len(ids) >= MIN_IDENTIFIERS else None


def holds_secret(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(MAX_BYTES)
    except OSError:
        return True
    return any(rx.search(text) for rx in SECRETS)


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


class Index:
    """The identifier sets of the store's comparable scripts, kept in `.state/index.json` by path, size and time,
    so a write reads only the scripts that changed since the last look."""

    def __init__(self, p4):
        self.p4 = p4
        self.file = os.path.join(skillex_dir(p4), STATE, "index.json")
        self.rows = {}
        self.dirty = False
        try:
            with open(self.file, encoding="utf-8") as f:
                self.rows = json.load(f)
        except (OSError, ValueError):
            self.rows = {}

    def get(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        k = key(path)
        row = self.rows.get(k)
        if row and row[0] == st.st_size and row[1] == st.st_mtime_ns:
            return set(row[2]) if row[2] is not None else None
        ids = identifiers(path)
        self.rows[k] = [st.st_size, st.st_mtime_ns, sorted(ids) if ids is not None else None]
        self.dirty = True
        return ids

    def save(self, live):
        """Write the index, keeping only the scripts in `live`. A failure costs only the cache."""
        keep = {k: v for k, v in self.rows.items() if k in live}
        if not self.dirty and len(keep) == len(self.rows):
            return
        try:
            write_json(self.p4, "index.json", keep)
        except OSError:
            pass


def state_dir(p4):
    """`.state/` in the store folder, which ignores itself so the store's git repository never tracks it."""
    d = os.path.join(skillex_dir(p4), STATE)
    os.makedirs(d, exist_ok=True)
    ignore = os.path.join(d, ".gitignore")
    if not os.path.isfile(ignore):
        with open(ignore, "w", encoding="utf-8", newline="\n") as f:
            f.write("*\n")
    return d


def write_json(p4, name, data):
    """Write `.state/<name>` whole or not at all, through a temp file of this process's own."""
    path = os.path.join(state_dir(p4), name)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def load_docs(p4, save=True):
    """Every comparable script of the store with its identifiers, as its session, path and identifier set."""
    index = Index(p4)
    docs, live = [], set()
    for s, base in sessions_of(p4):
        for p in scripts_of(base):
            live.add(key(p))
            ids = index.get(p)
            if ids:
                docs.append((s, p, ids))
    if save:
        index.save(live)
    return docs


def cluster(p4, path, session):
    """The scripts linked to `path` across sessions, each as its session and path: those that match it, those that
    match them, and so on, where a link joins two scripts of different sessions that share SIMILAR of their
    identifiers."""
    docs = load_docs(p4)
    mine = next((ids for s, p, ids in docs if key(p) == key(path)), None)
    if mine is None:
        mine = identifiers(path)
    if not mine:
        return []
    members, rest, i = [(session, path, mine)], [d for d in docs if key(d[1]) != key(path)], 0
    while i < len(members):
        s0, _, ids0 = members[i]
        linked = [d for d in rest if d[0] != s0 and jaccard(ids0, d[2]) >= SIMILAR]
        members += linked
        rest = [d for d in rest if d not in linked]
        i += 1
    return [(s, p) for s, p, _ in members[1:]]


# --------------------------------------------------------------------------------------------------- writing a skill

def kebab(stem):
    s = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return s[:64].strip("-") or "brewed"


def stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def pick_name(paths, own):
    """The commonest file stem of the matching scripts, the written file's own stem on a tie."""
    counts = {}
    for p in paths:
        k = kebab(stem(p))
        counts[k] = counts.get(k, 0) + 1
    mine = kebab(stem(own))
    return max(counts, key=lambda k: (counts[k], k == mine, k))


def header_of(path, limit=40):
    """The script's own description: a Python docstring, or the comment block at the top of any other script."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return ""
    if path.lower().endswith(".py"):
        m = re.match(r'\s*(?:#[^\n]*\n\s*)*[rRuU]?("""|\'\'\')(.*?)\1', text, re.S)
        if m:
            return "\n".join(m.group(2).strip().splitlines()[:limit])
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("#!") and not lines:
            continue
        if s.startswith(("#", "//", "::", "REM ", "rem ")):
            lines.append(re.sub(r"^(#+|//|::|REM|rem)\s?", "", s))
        elif s == "" and not lines:
            continue
        else:
            break
    return "\n".join(lines[:limit]).strip()


def first_sentence(text):
    flat = " ".join(text.split())
    m = re.match(r"(.+?[.!?])(\s|$)", flat)
    s = (m.group(1) if m else flat)[:240]
    return s.replace("<", "&lt;").replace(">", "&gt;")


RUNNERS = {".py": "python", ".sh": "sh", ".ps1": "pwsh -File", ".js": "node", ".mjs": "node", ".cjs": "node",
           ".ts": "npx tsx", ".bat": "cmd /c", ".cmd": "cmd /c"}


def where_section(rels):
    return "\n".join(["## Where it was written", "", *[f"- `{r}`" for r in rels], ""])


def skill_text(name, newest, rels):
    header = header_of(newest)
    base = os.path.basename(newest)
    runner = RUNNERS.get(os.path.splitext(base)[1].lower(), "")
    desc = first_sentence(header) if header else f"A script this project's sessions keep writing, kept as {base}."
    n = len({r.split("/")[1] if r.startswith("tmp/") else r.split("/")[0] for r in rels})
    lines = [
        "---",
        f"name: {name}",
        f"description: {json.dumps(desc + f'{BREWED}{n} sessions of this project.')}",
        "---",
        "",
        f"# {name}",
        "",
        "This project's sessions wrote this script again and again in their scratch, so it is kept here as a skill.",
        f"The newest version is `${{CLAUDE_SKILL_DIR}}/scripts/{base}`: run it with `{runner} \"${{CLAUDE_SKILL_DIR}}/scripts/{base}\"` and the arguments its usage names, or copy it and adapt it to the task.",
        "",
    ]
    if header:
        lines += ["## What the script says it does", "", *["    " + ln if ln else "" for ln in header.splitlines()], ""]
    return "\n".join(lines) + "\n" + where_section(rels)


def store_skills(p4):
    d = skillex_dir(p4)
    if not os.path.isdir(d):
        return []
    return [n for n in sorted(os.listdir(d)) if not n.startswith(".") and os.path.isfile(os.path.join(d, n, "SKILL.md"))]


def read_sources(p4, name):
    try:
        with open(os.path.join(skillex_dir(p4), name, "sources.txt"), encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return []


def owner_skill(p4, rels):
    """The store skill whose recorded sources share a script with `rels`, if any."""
    want = set(rels)
    for n in store_skills(p4):
        if want & set(read_sources(p4, n)):
            return n
    return None


def free_name(p4, name):
    """`name`, or `name-2` and onward, so it is neither a store skill nor a project's own skill in `.claude/skills/`,
    and stays within 64 characters."""
    taken = set(store_skills(p4))
    own = project_skills(p4)
    if os.path.isdir(own):
        taken |= {n for n in os.listdir(own) if not os.path.isfile(os.path.join(own, n, MARKER))}
    if name not in taken:
        return name
    i = 2
    while True:
        suffix = f"-{i}"
        candidate = name[:64 - len(suffix)].rstrip("-") + suffix
        if candidate not in taken:
            return candidate
        i += 1


def write_skill(p4, name, newest, sources):
    """Write `skillex/<name>/` for a new skill, or refresh an existing one.

    A new skill gets SKILL.md, the newest script in `scripts/` and `sources.txt`. A refresh adds the new sources to
    `sources.txt` and to the "Where it was written" section, and puts the newest version in place of the script of
    the same kind under the name it was first kept by, so whatever else SKILL.md says, edited by hand or not, stays."""
    t = real(os.path.join(p4, "temportal"))
    d = os.path.join(skillex_dir(p4), name)
    scripts = os.path.join(d, "scripts")
    os.makedirs(scripts, exist_ok=True)
    rels = []
    for r in read_sources(p4, name) + [os.path.relpath(real(p), t).replace(os.sep, "/") for _, p in sources]:
        if r not in rels:
            rels.append(r)
    md = os.path.join(d, "SKILL.md")
    if not os.path.isfile(md):
        with open(md, "w", encoding="utf-8", newline="\n") as f:
            f.write(skill_text(name, newest, rels))
        shutil.copyfile(newest, os.path.join(scripts, os.path.basename(newest)))
    else:
        with open(md, encoding="utf-8") as f:
            text = f.read()
        new = where_section(rels)
        m = re.search(r"^## Where it was written\n.*?(?=^## |\Z)", text, re.S | re.M)
        if m:
            text = text[:m.start()] + new + ("\n" if text[m.end():] else "") + text[m.end():]
        else:
            text = text.rstrip("\n") + "\n\n" + new
        with open(md, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        ext = os.path.splitext(newest)[1].lower()
        named = re.findall(r"\$\{CLAUDE_SKILL_DIR\}/scripts/([^`\"\s]+)", text)
        kept = [f for f in named if os.path.splitext(f)[1].lower() == ext]
        kept += sorted(f for f in os.listdir(scripts) if os.path.splitext(f)[1].lower() == ext and f not in kept)
        shutil.copyfile(newest, os.path.join(scripts, kept[0] if kept else os.path.basename(newest)))
    with open(os.path.join(d, "sources.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(r + "\n" for r in rels))
    return d


# ------------------------------------------------------------------------------------------- searching for similar

def stem_word(w):
    for end in ("ing", "ed", "es", "s"):
        if len(w) > len(end) + 2 and w.endswith(end):
            return w[:-len(end)]
    return w


def words(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower().replace("_", " ").replace("-", " ")
    return {stem_word(w) for w in WORD.findall(text) if w not in STOP_WORDS}


def front(text):
    """name and description of a SKILL.md, read from its frontmatter."""
    m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    meta = m.group(1) if m else ""
    name = re.search(r"^name:\s*(.+)$", meta, re.M)
    desc = re.search(r"^description:\s*(.+)$", meta, re.M)
    return (name.group(1).strip().strip("\"'") if name else ""), (desc.group(1).strip().strip("\"'") if desc else "")


def search_roots(p4):
    env = os.environ.get("P4_SKILLEX_SEARCH_ROOTS")
    if env is not None:
        return [r for r in env.split(os.pathsep) if r]
    home = os.path.expanduser("~")
    return [os.path.join(home, ".claude", "skills"), os.path.join(home, ".claude", "plugins"),
            project_skills(p4), skillex_dir(p4)]


def skill_label(path):
    """How a found SKILL.md is invoked: `<plugin>:<skill>` inside a plugin, `anthropic-skills:<skill>` for a skill
    synced from the claude.ai account, else the skill folder's name."""
    d = os.path.dirname(path)
    skill = os.path.basename(d)
    up = os.path.dirname(d)
    if os.path.basename(os.path.dirname(up)) == "synced":
        return f"anthropic-skills:{skill}"            # a skill enabled for the claude.ai account
    if os.path.basename(up) == "skills":
        root = os.path.dirname(up)
        manifest = os.path.join(root, ".claude-plugin", "plugin.json")
        if os.path.isfile(manifest):
            try:
                with open(manifest, encoding="utf-8") as f:
                    return f"{json.load(f).get('name') or os.path.basename(root)}:{skill}"
            except (OSError, ValueError):
                return f"{os.path.basename(root)}:{skill}"
    return skill


def search_similar(p4, skill_dir):
    """Existing skills like the one in `skill_dir`, as [{name, path, score}], best first.

    Runs only after the skill is written: it reads the skill's own SKILL.md and script to know what to look for."""
    me = os.path.join(skill_dir, "SKILL.md")
    with open(me, encoding="utf-8") as f:
        mine_text = f.read()
    name, desc = front(mine_text)
    desc = desc.split(BREWED)[0]
    script = ""
    sd = os.path.join(skill_dir, "scripts")
    for s in os.listdir(sd) if os.path.isdir(sd) else []:
        script += header_of(os.path.join(sd, s))
    mine = words(name + " " + desc + " " + script)
    if not mine:
        return []
    deadline = time.monotonic() + SEARCH_DEADLINE_S
    own = key(skill_dir)
    seen, candidates = set(), []
    walks = (os.walk(root) for root in search_roots(p4) if os.path.isdir(root))
    for r, ds, fs in (step for walk in walks for step in walk):
        if time.monotonic() > deadline or len(candidates) >= SEARCH_MAX_FILES:
            break                                        # every root is left once the time is up
        ds[:] = [d for d in ds if d not in SKIP_DIRS and d != ".git" and d != STATE]
        if "SKILL.md" not in fs:
            continue
        if key(r) == own or os.path.isfile(os.path.join(r, MARKER)):
            continue
        p = os.path.join(r, "SKILL.md")
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                head = f.read(4000)
        except OSError:
            continue
        their_name, their_desc = front(head)
        their_desc = their_desc.split(BREWED)[0]
        theirs = words(their_name + " " + their_desc + " " + os.path.basename(r))
        label = skill_label(p)
        if theirs and (label, their_desc) not in seen:
            seen.add((label, their_desc))
            candidates.append((label, p, their_desc, theirs))
    # Each word weighs by how rare it is among the skills found, so a word every skill says counts for little.
    df = {}
    for c in candidates:
        for w in c[3]:
            df[w] = df.get(w, 0) + 1
    total = len(candidates) + 1

    def weight(w):
        return math.log((total + 1) / (df.get(w, 0) + 1)) + 1.0

    norm_mine = sum(weight(w) ** 2 for w in mine) ** 0.5
    found = []
    for label, p, their_desc, theirs in candidates:
        shared = sum(weight(w) ** 2 for w in mine & theirs)
        score = shared / (norm_mine * sum(weight(w) ** 2 for w in theirs) ** 0.5)
        if score >= SEARCH_MIN_SCORE:
            found.append({"name": label, "path": shown(p, p4), "score": round(score, 3), "description": their_desc[:200]})
    found.sort(key=lambda m: -m["score"])
    return found[:SEARCH_KEEP]


def shown(path, p4):
    """A path as a store file records it: relative to the project inside it, `~/...` under the home folder, and
    otherwise none, so no absolute path and no user name is written."""
    project = os.path.dirname(os.path.dirname(os.path.abspath(p4)))
    for base, prefix in ((project, ""), (os.path.expanduser("~"), "~/")):
        try:
            if os.path.normcase(os.path.commonpath([os.path.abspath(path), base])) == os.path.normcase(base):
                return prefix + os.path.relpath(path, base).replace(os.sep, "/")
        except ValueError:
            continue
    return None


def link_similar(skill_dir, similar):
    """Write the links: `similar.json`, and a "Similar existing skills" section at the end of SKILL.md."""
    with open(os.path.join(skill_dir, "similar.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(similar, f, indent=2)
    if not similar:
        return
    me = os.path.join(skill_dir, "SKILL.md")
    with open(me, encoding="utf-8") as f:
        text = f.read()
    i = text.find("\n## Similar existing skills")
    if i >= 0:
        text = text[:i + 1]
    lines = ["## Similar existing skills", "",
             "These existing skills do work like this one. Read the one that fits before running this skill's script, and use it where it already does the task.", ""]
    for m in similar:
        at = f", at `{m['path']}`" if m["path"] else ""
        lines.append(f"- `{m['name']}`{at}: {m['description']}")
    with open(me, "w", encoding="utf-8", newline="\n") as f:
        f.write(text.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n")


# --------------------------------------------------------------------------------------------------------- copying

def mirror(p4, names=None):
    """Copy store skills into the project's `.claude/skills/`. Returns the names copied or removed."""
    src = skillex_dir(p4)
    dst = project_skills(p4)
    os.makedirs(dst, exist_ok=True)
    changed = []
    store = set(store_skills(p4))
    for n in sorted(store if names is None else set(names) & store):
        target = os.path.join(dst, n)
        if os.path.isdir(target) and not os.path.isfile(os.path.join(target, MARKER)):
            continue                                   # the project's own skill of that name: never touched
        files = {}
        for r, ds, fs in os.walk(os.path.join(src, n)):
            for f in fs:
                if f in ("sources.txt",):
                    continue
                p = os.path.join(r, f)
                files[os.path.relpath(p, os.path.join(src, n))] = p
        there = set()
        for r, ds, fs in os.walk(target):
            there |= {os.path.relpath(os.path.join(r, f), target) for f in fs if f not in (MARKER, COPY_IGNORE)}
        same = os.path.isdir(target) and there == set(files) and all(
            _same_bytes(p, os.path.join(target, rel)) for rel, p in files.items())
        if same:
            continue
        staging = os.path.join(state_dir(p4), "staging", f"{n}.{os.getpid()}")
        if os.path.isdir(staging):
            shutil.rmtree(staging)
        for rel, p in files.items():
            os.makedirs(os.path.dirname(os.path.join(staging, rel)), exist_ok=True)
            shutil.copyfile(p, os.path.join(staging, rel))
        with open(os.path.join(staging, MARKER), "w", encoding="utf-8", newline="\n") as f:
            f.write(f".claude/p4/skillex/{n}\n")
        with open(os.path.join(staging, COPY_IGNORE), "w", encoding="utf-8", newline="\n") as f:
            f.write("*\n")
        if os.path.isdir(target):
            set_aside(p4, target)
        try:
            os.replace(staging, target)
        except OSError:                                  # another session placed its copy first
            shutil.rmtree(staging, ignore_errors=True)
        changed.append(n)
    if names is None and os.path.isdir(dst):
        for n in sorted(os.listdir(dst)):
            if n not in store and os.path.isfile(os.path.join(dst, n, MARKER)):
                set_aside(p4, os.path.join(dst, n))    # its store skill is gone
                changed.append(n)
    clear_aside(p4)
    return changed


def set_aside(p4, target):
    """Move a copy out of `.claude/skills/` whole, marker and all, into `.state/aside/`; clear_aside deletes it."""
    aside = os.path.join(state_dir(p4), "aside")
    os.makedirs(aside, exist_ok=True)
    os.replace(target, os.path.join(aside, f"{os.path.basename(target)}.{os.getpid()}.{time.time_ns()}"))


def clear_aside(p4):
    """Delete what set_aside moved, and a staging folder an ended run left; a failure only waits for the next run."""
    for sub in ("aside", "staging"):
        d = os.path.join(skillex_dir(p4), STATE, sub)
        for n in os.listdir(d) if os.path.isdir(d) else []:
            if sub == "aside" or not n.endswith(f".{os.getpid()}"):
                shutil.rmtree(os.path.join(d, n), ignore_errors=True)


def _same_bytes(a, b):
    try:
        with open(a, "rb") as f, open(b, "rb") as g:
            return f.read() == g.read()
    except OSError:
        return False


# ------------------------------------------------------------------------------------------------------- the watcher

def brew(p4, path):
    """Look at one written file. Returns the skill's name, whether it was created and what is similar when a skill was written, else None."""
    where = where_in_temportal(p4, path)
    if not where or not os.path.isfile(path):
        return None
    session, base = where
    path = real(path)
    if not comparable(base, path) or holds_secret(path):
        return None
    found = cluster(p4, path, session)
    if len({session} | {s for s, _ in found}) < MIN_SESSIONS:
        return None
    t = real(os.path.join(p4, "temportal"))
    sources = [(session, path)] + found
    rels = [os.path.relpath(real(p), t).replace(os.sep, "/") for _, p in sources]
    name = owner_skill(p4, rels)
    created = name is None
    if created:
        name = free_name(p4, pick_name([p for _, p in sources], path))
    d = write_skill(p4, name, path, sources)
    similar = []
    if created:
        similar = search_similar(p4, d)
        link_similar(d, similar)
    mirror(p4, [name])
    return name, created, similar


def notice(results):
    out = []
    for name, created, similar in results:
        verb = "wrote" if created else "refreshed"
        line = f"p4-skillex: {verb} the skill `{name}` at .claude/p4/skillex/{name}/SKILL.md from scripts this project's sessions keep writing; it is copied to .claude/skills/{name}/."
        if similar:
            line += " Similar existing skills: " + ", ".join(f"`{m['name']}`" for m in similar) + "."
        out.append(line)
    return "\n".join(out)


def session_file(p4, sid):
    return os.path.join(skillex_dir(p4), STATE, "sessions", f"{kebab(sid)}.json")


def read_session(p4, sid):
    """A session's own watcher state: `since`, the time of its last look, and `looked`, the scripts the Write hook
    already looked at since then with their modification times. Each session has its own file, so no two write one."""
    try:
        with open(session_file(p4, sid), encoding="utf-8") as f:
            st = json.load(f)
        return {"since": float(st.get("since", 0)), "looked": dict(st.get("looked") or {})}
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def write_session(p4, sid, st):
    os.makedirs(os.path.join(state_dir(p4), "sessions"), exist_ok=True)
    write_json(p4, os.path.join("sessions", f"{kebab(sid)}.json"), st)


def cmd_start(p4, payload):
    os.makedirs(skillex_dir(p4), exist_ok=True)
    made = not os.path.isdir(project_skills(p4))
    changed = mirror(p4)
    sid = payload.get("session_id")
    if sid and read_session(p4, sid) is None:
        write_session(p4, sid, {"since": time.time(), "looked": {}})
    if changed or made:
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "reloadSkills": True}}
    return None


def cmd_write(p4, payload):
    path = (payload.get("tool_input") or {}).get("file_path")
    if not path:
        return None
    r = brew(p4, path)
    sid = payload.get("session_id")
    if sid and where_in_temportal(p4, path):
        st = read_session(p4, sid) or {"since": time.time(), "looked": {}}
        try:
            st["looked"][key(path)] = os.stat(path).st_mtime_ns
            write_session(p4, sid, st)
        except OSError:
            pass
    if not r:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": notice([r])}}


def cmd_stop(p4, payload):
    """Look at the session's scripts changed since its last look that the Write hook has not seen, oldest first,
    so the newest version is the one a skill keeps. The new time of the look is saved before any script is read, so
    a Stop cut short by its timeout never makes the next one start over."""
    sid = payload.get("session_id")
    if not sid:
        return None
    st = read_session(p4, sid)
    write_session(p4, sid, {"since": time.time(), "looked": {}})
    if st is None:                                       # no start was recorded: nothing to compare against
        return None
    base = os.path.join(p4, "temportal", "tmp", sid)
    changed = []
    if os.path.isdir(base):
        for p in scripts_of(base):
            try:
                m = os.stat(p)
            except OSError:
                continue
            if m.st_mtime > st["since"] and st["looked"].get(key(p)) != m.st_mtime_ns:
                changed.append((m.st_mtime_ns, p))
    results = [r for r in (brew(p4, p) for _, p in sorted(changed)) if r]
    if results:
        return {"systemMessage": notice(results)}
    return None


def scan(p4):
    """What is brewing in a store now: clusters of matching scripts across at least MIN_SESSIONS sessions."""
    docs = load_docs(p4, save=False)
    parent = list(range(len(docs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(docs)):
        for j in range(i + 1, len(docs)):
            if docs[i][0] != docs[j][0] and jaccard(docs[i][2], docs[j][2]) >= SIMILAR:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(len(docs)):
        groups.setdefault(find(i), []).append(docs[i])
    out = []
    for g in groups.values():
        if len({s for s, _, _ in g}) >= MIN_SESSIONS:
            newest = max(g, key=lambda d: os.path.getmtime(d[1]))
            out.append((pick_name([p for _, p, _ in g], newest[1]), sorted(p for _, p, _ in g)))
    return sorted(out)


def main():
    args = sys.argv[1:]
    sub = args[0] if args else ""
    p4 = None
    if "--p4" in args:
        i = args.index("--p4")
        p4 = args[i + 1] if i + 1 < len(args) else None
        args = args[:i] + args[i + 2:]
    if sub in ("scan", "brew"):
        p4 = p4 or store_of(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        if sub == "scan":
            for name, paths in scan(p4):
                print(f"{name}: {len(paths)} scripts")
                for p in paths:
                    print(f"  {p}")
            return 0
        if len(args) < 2:
            print("usage: skillex.py brew <file> [--p4 <store>]")
            return 2
        r = brew(p4, args[1])
        print(notice([r]) if r else "p4-skillex: nothing is brewing in that file")
        return 0
    handlers = {"start": cmd_start, "write": cmd_write, "stop": cmd_stop}
    if sub not in handlers:
        print(f"p4-skillex: unknown command '{sub}'; nothing was done")
        return 0
    try:
        payload = payload_from_stdin()
        out = handlers[sub](p4 or store_of(project_root(payload)), payload)
        if out:
            print(json.dumps(out))
    except Exception as e:  # a broken hook never blocks a call
        print(f"p4-skillex {sub}: {type(e).__name__}: {e}; nothing more was done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
