"""relay.py: linked sessions kept in step while they work, modelled on the node tree of phi_rank/tree.py.

phi_rank's tree has K nodes, each owning a shard of the store; a parent formed from its children; rounds shipped as
deltas on a shared anchor; `medium` routing a question to the node that owns it and `high` consulting all. A session
tree is kept the same way (.docs/p4/recall-node.md, "The relay"):

  shard   what a session alone may change: paths or globs, `phi.py shard <paths>`, kept in its session.json as
          `shard`. A parent's shard covers its children's. Two sessions under the same parent whose shards overlap
          are told so at once, both of them: the one declaring now in the command's output, the other at its next
          message.
  delta   a turn's change, kept on its row in turns.jsonl at Stop: the branch heads of the repositories it edited
          in, the files it changed, and its `deprecates:` and `replaces:` notes written since its last turn, with
          the paths they name.
  anchor  <parent's folder>/anchor.json: the latest delta of each of the parent's children and the parent's own
          `deprecates:` and `replaces:` notes, with a version that goes up when any of that changes. It is made
          again at the Stop of the parent or any of its children.
  rebase  at every message a session is given, including the app's side-session events: when its parent's anchor
          is newer than the version it last saw, the other nodes' deprecations and replacements, first and in full,
          then their other deltas, cut evenly to what is left of the hook's room. And a warning, before any tool
          runs, for each of its uncommitted files or shard paths that a newer deprecation or replacement names,
          and for each of its uncommitted files inside another node's shard: stop that work and message that
          node. Nothing when nothing changed; a warning is given once.
  route   a message that names a path inside another node's shard is that node's: the session is told to send it
          there with SendMessage. Only a message no shard covers gets a new forked session (phi.new_task_text).

Every function takes the store's home and session ids as phi.py has them; phi.py calls them from its hooks.
"""

import glob
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys

MARKS = ("deprecates:", "replaces:")
PATH_RE = re.compile(r"`([^`\s]+)`|((?:[A-Za-z]:)?[\w.~-]*[\\/][\w.\\/*~-]+)")
GIT_S = 5                        # what one git call may take inside a hook


# --- files ---------------------------------------------------------------------------------------------------------

def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"            # one writer's temp file never another's
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _rows(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    out.append(r)
    except OSError:
        pass
    return out


def _dir(home, sid):
    return os.path.join(home, "phi", "sessions", re.sub(r"[^A-Za-z0-9_.-]", "_", str(sid or ""))[:80])


def _session(home, sid):
    return _read_json(os.path.join(_dir(home, sid), "session.json")) if sid else {}


def _parent(s):
    sp = s.get("spawnedFrom") if isinstance(s, dict) else None
    return str(sp.get("sessionId") or "") if isinstance(sp, dict) else ""


def _sessions(home):
    """{sessionId: session.json} of every session in the store."""
    out = {}
    base = os.path.join(home, "phi", "sessions")
    try:
        names = os.listdir(base)
    except OSError:
        return out
    for n in names:
        d = _read_json(os.path.join(base, n, "session.json"))
        if d.get("sessionId"):
            out[d["sessionId"]] = d
    return out


def _title(s):
    return str(s.get("title") or s.get("sessionId") or "")[:60]


RECORD = None                    # phi.app_record, set by phi at import; read lazily otherwise
ROOTED = None                    # phi.record_in, the record looked up in the app folder it was first found in


def archived_in_app(s):
    """True when the app archived a session (`isArchived` in its record), or its record has gone from the app folder
    it was first found in on this machine. A session no app runs, or one whose folder this machine lacks (a store
    synced from another machine), is never taken as archived by a missing record."""
    sid = str(s.get("sessionId") or "")
    if not sid.startswith("local_"):
        return False
    global RECORD, ROOTED
    if RECORD is None:
        import phi
        RECORD, ROOTED = phi.app_record, phi.record_in
    root = str(s.get("appRoot") or "")
    if root and os.path.isdir(root):
        rec = ROOTED(root, sid)
        return not rec or bool(rec.get("isArchived"))
    return bool(RECORD(sid).get("isArchived"))


def gone(home, s):
    """True when a session is out of the live tree: stale, finished and disposable, or archived in the app. An
    archive seen in the app is kept in its session.json, so the other machines a store syncs to see it too."""
    if not isinstance(s, dict) or not s.get("sessionId"):
        return True
    if s.get("stale") or s.get("doneRetired") or s.get("archived"):
        return True
    if archived_in_app(s):
        path = os.path.join(_dir(home, s["sessionId"]), "session.json")
        disk = _read_json(path)
        if disk and not disk.get("archived"):
            import time
            disk["archived"] = time.strftime("%Y-%m-%d %H:%M")
            _write_json(path, disk)
        s["archived"] = True
        return True
    return False


# --- paths -----------------------------------------------------------------------------------------------------------

def norm(p, base=""):
    """A path or glob as one form: absolute when a base is given, forward slashes, no trailing slash, case folded
    on Windows."""
    p = str(p or "").strip().strip("'\"")
    if not p:
        return ""
    p = p.replace("\\", "/")
    # /e/x as Git Bash writes E:/x, and /mnt/e/x as WSL does, before the absolute test: on Windows since Python 3.13 a
    # path with one leading slash is not absolute, so /e/x was joined onto the base (P5)
    p = re.sub(r"^/mnt/([a-zA-Z])(?=/|$)", lambda m: m.group(1).upper() + ":", p)
    p = re.sub(r"^/([a-zA-Z])(?=/|$)", lambda m: m.group(1).upper() + ":", p)
    if base and not os.path.isabs(p) and not re.match(r"^[A-Za-z]:", p):
        p = os.path.join(base, p).replace("\\", "/")
    p = re.sub(r"/+", "/", p).rstrip("/")
    return p.lower() if os.name == "nt" else p


def _root(glob):
    """The directory part of a glob before its first wildcard."""
    cut = re.split(r"[*?\[]", glob, maxsplit=1)[0]
    return cut.rstrip("/") if cut != glob else glob


def covers(pattern, path):
    """True when `path` lies in `pattern`: the same path, a path under it, or a glob match."""
    if not pattern or not path:
        return False
    if path == pattern or path.startswith(pattern + "/"):
        return True
    return any(c in pattern for c in "*?[") and (fnmatch.fnmatchcase(path, pattern) or
                                                 fnmatch.fnmatchcase(path, pattern.rstrip("*").rstrip("/") + "/*"))


def overlap(a, b):
    """True when two shard entries can name the same file."""
    ra, rb = _root(a), _root(b)
    return covers(a, b) or covers(b, a) or covers(ra, rb) or covers(rb, ra)


def paths_in(text, base=""):
    """The paths a note names: in backticks, or written with a slash."""
    out = []
    text = re.sub(r"[A-Za-z][\w+.-]*://\S+", " ", str(text or ""))       # a URL is not a path
    for m in PATH_RE.finditer(text):
        p = m.group(1) or m.group(2)
        if p and ("/" in p or "\\" in p or "." in p) and not p.startswith(("http:", "https:")):
            n = norm(p.rstrip(".,;:)"), base)
            if n and n not in out and drive_ok(n):
                out.append(n)
    return out


# --- shards ----------------------------------------------------------------------------------------------------------

def shard_of(s):
    return [x for x in (s.get("shard") or []) if isinstance(x, str) and x]


def set_shard(home, sid, paths, base):
    """Keep `paths` as the session's shard -> the lines to print: one per sibling whose shard overlaps. The sibling
    is told at its next message too."""
    path = os.path.join(_dir(home, sid), "session.json")
    s = _read_json(path)
    if not s:
        raise ValueError("no such session in this store")
    shard = [n for n in (norm(p, base) for p in paths) if n]
    if not shard:
        raise ValueError("name the paths or globs this session alone may change")
    s["shard"] = shard
    _write_json(path, s)
    import time                                   # the siblings see the new shard at their next message
    make_anchor(home, _parent(s), time.strftime("%Y-%m-%d %H:%M"))
    lines = []
    for o, os_ in _siblings(home, s).items():
        hits = sorted({f"{a} and {b}" for a in shard for b in shard_of(os_) if overlap(a, b)})
        if not hits:
            continue
        lines.append(f"overlaps the shard of \"{_title(os_)}\" ({o}): {'; '.join(hits[:5])}. Agree with that "
                     f"session, by SendMessage to {o}, who changes what, before either edits it.")
        warn(home, o, f"shard:{sid}:{','.join(shard)}",
             f"the session \"{_title(s)}\" ({sid}) declared a shard that overlaps yours: {'; '.join(hits[:5])}. "
             f"Agree with it, by SendMessage to {sid}, who changes what, before either edits it.")
    return lines


def _siblings(home, s):
    """The live sessions beside this one: the same parent's, or for a top session every other top session in the
    store's root, detached ones included, so tops relay to each other as siblings. An archived one is gone."""
    p = _parent(s)
    return {k: v for k, v in _sessions(home).items() if k != s.get("sessionId") and _parent(v) == p
            and not gone(home, v)}


def warn(home, sid, key, text):
    """A warning kept for a session's next message, once per key."""
    path = os.path.join(_dir(home, sid), "session.json")
    s = _read_json(path)
    if not s:
        return False
    told = s.setdefault("relayWarned", [])
    if key in told:
        return False
    pend = s.setdefault("relayPending", [])
    if any(isinstance(w, dict) and w.get("text") == text for w in pend):
        return False                              # R7: the same words already wait for this session
    up = re.match(r"^plan:([^:]+):[^:]+:up$", key)
    same = [w for w in pend if isinstance(w, dict) and up and re.match(rf"^plan:{re.escape(up.group(1))}:[^:]+:up$",
                                                                      str(w.get("key") or ""))]
    if same:                                      # RF1: one line for a child's revisions since the last look
        n = sum(int(w.get("count") or 1) for w in same) + 1
        for w in same:
            pend.remove(w)
            told.append(w.get("key"))
        text = re.sub(r"revised its plan:", f"revised its plan {n} times since you last looked; now:", text, count=1)
        pend.append({"key": key, "text": text, "count": n})
    else:
        pend.append({"key": key, "text": text})
    turns = [w for w in pend if isinstance(w, dict) and str(w.get("key", "")).startswith("turn:")]
    for old in turns[:-TURN_WARNINGS]:                  # R6: the newest relayed turn reports only
        pend.remove(old)
        told.append(old.get("key"))
    _write_json(path, s)
    return True


TURN_WARNINGS = 3          # relayed turn reports kept for one session's next message; older ones are dropped as told


# --- deltas ----------------------------------------------------------------------------------------------------------

def _git(cwd, *args):
    try:
        return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=GIT_S)
    except (OSError, subprocess.SubprocessError):
        return None


def drive_ok(p):
    """False for a path on a drive this machine does not have: a stored mark's path read wrongly once, such as
    `s:/replaces`, must never reach a filesystem walk (H1)."""
    m = re.match(r"^([A-Za-z]):", str(p or ""))
    return not m or os.path.isdir(m.group(1) + ":/")


def repo_of(path):
    if not drive_ok(path):
        return ""
    d = path if os.path.isdir(path) else os.path.dirname(path)
    while d and not os.path.isdir(d):
        up = os.path.dirname(d)
        if up == d:                                     # a drive or root that does not exist: no repository
            return ""
        d = up
    r = _git(d, "rev-parse", "--show-toplevel") if d else None
    return norm(r.stdout.strip()) if r and r.returncode == 0 and r.stdout.strip() else ""


def heads(repos):
    """['<repo>@<branch> <sha8>'] of each repository."""
    out = []
    for repo in sorted(set(r for r in repos if r)):
        b = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        h = _git(repo, "rev-parse", "--short=8", "HEAD")
        if b and h and b.returncode == 0 and h.returncode == 0:
            out.append(f"{repo}@{b.stdout.strip()} {h.stdout.strip()}")
    return out


def delta(home, s, files, cwd, since=""):
    """A turn's delta: the heads of the repositories it edited in, the files, and its marked notes since `since`."""
    sid = s.get("sessionId") or ""
    files = sorted({norm(f, cwd) for f in files if f})
    repos = {repo_of(f) for f in files} | ({repo_of(cwd)} if cwd else set())
    marked = []
    for n in _rows(os.path.join(_dir(home, sid), "notes.jsonl")):
        claim = str(n.get("claim") or "")
        if claim.lower().startswith(MARKS) and (not since or str(n.get("time") or "") >= since):
            marked.append({"claim": claim, "source": str(n.get("source") or ""), "time": str(n.get("time") or ""),
                           "paths": paths_in(claim, cwd)})
    return {"heads": heads(repos), "files": files, "marks": marked}


# --- anchors ---------------------------------------------------------------------------------------------------------

def anchor_path(home, parent):
    """<parent>/anchor.json; for the top sessions, which nobody started, phi/anchor.json: the root of the tree."""
    if not parent:
        return os.path.join(home, "phi", "anchor.json")
    return os.path.join(_dir(home, parent), "anchor.json")


def make_anchor(home, parent, now):
    """Make <parent>/anchor.json again from the latest delta of each child and the parent's own marked notes, or
    with no parent the root's from the top sessions' marks and plans; its version goes up only when that content
    changed. Returns the anchor."""
    import plans                                  # the plan tree: each node's steps, statuses and current step
    root = not parent                             # the top sessions: only their marks and plans, never heads or files
    every = _sessions(home)
    nodes = {}
    for sid, s in every.items():
        if _parent(s) != parent or gone(home, s):
            continue
        last = None
        for r in reversed(_rows(os.path.join(_dir(home, sid), "turns.jsonl"))):
            if isinstance(r.get("delta"), dict):
                last = r
                break
        marks = _all_marks(home, sid)
        plan = plans.summary(home, sid)
        if last or marks or shard_of(s) or plan:
            d = (last or {}).get("delta") or {}
            nodes[sid] = {"title": _title(s), "time": str((last or {}).get("time") or ""),
                          "heads": [] if root else d.get("heads") or [], "files": [] if root else d.get("files") or [],
                          "marks": marks,
                          "shard": shard_of(s), "plan": plan, "root": str(s.get("rootStep") or "")}
    own = {} if root else {"title": _title(every.get(parent, {})), "marks": _all_marks(home, parent),
                           "shard": shard_of(every.get(parent, {})), "plan": plans.summary(home, parent)}
    if not root:                                  # a finished child a newer note supersedes is fenced off now
        marks_now = [(k, n.get("title") or k, m) for k, n in nodes.items() for m in n.get("marks") or []]
        marks_now += [(parent, own.get("title") or parent, m) for m in own.get("marks") or []]
        for k in list(nodes):
            if not finished(home, k):
                continue
            by = superseded(home, k, every[k], [x for x in marks_now if x[0] != k])
            if by:
                old_v = int(_read_json(anchor_path(home, parent)).get("version") or 0)
                retire(home, parent, k, every[k], by, old_v + 1, now)
                del nodes[k]
    body = {"nodes": nodes, "parent": own}
    digest = hashlib.sha1(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
    path = anchor_path(home, parent)
    old = _read_json(path)
    if old.get("digest") == digest:
        return old
    out = {"version": int(old.get("version") or 0) + 1, "time": now, "digest": digest, **body,
           "seenAt": {k: v.get("time", "") for k, v in nodes.items()}}
    out["changedAt"] = dict(old.get("changedAt") or {})
    for k, v in nodes.items():
        before = (old.get("nodes") or {}).get(k)
        if before != v:
            out["changedAt"][k] = int(out["version"])
    if (old.get("parent") or {}) != own:
        out["changedAt"][parent] = int(out["version"])
    _write_json(path, out)
    return out


def _all_marks(home, sid):
    s = _session(home, sid)
    base = s.get("cwd") or ""
    return [{"claim": str(n.get("claim") or ""), "source": str(n.get("source") or ""),
             "time": str(n.get("time") or ""), "paths": paths_in(n.get("claim"), base)}
            for n in _rows(os.path.join(_dir(home, sid), "notes.jsonl"))
            if str(n.get("claim") or "").lower().startswith(MARKS)]


# --- the rebase check ------------------------------------------------------------------------------------------------

def uncommitted(files):
    """The files among `files` that git shows changed and not committed."""
    out, by_repo = [], {}
    for f in files:
        r = repo_of(f)
        if r:
            by_repo.setdefault(r, []).append(f)
    for repo, fs in by_repo.items():
        st = _git(repo, "status", "--porcelain", "-z", "--untracked-files=all")
        if not st or st.returncode != 0:
            continue
        dirty = set()
        for item in st.stdout.split("\0"):
            if len(item) > 3:
                dirty.add(norm(item[3:], repo))
        out += [f for f in fs if f in dirty]
    return sorted(set(out))


def edited_files(home, sid):
    """Every file the session's kept turns changed."""
    out = set()
    for r in _rows(os.path.join(_dir(home, sid), "turns.jsonl")):
        out.update((r.get("delta") or {}).get("files") or [])
    return sorted(out)


def mark_key(nid, m):
    return f"{nid}:{m.get('time')}:" + hashlib.sha1(str(m.get('claim') or '').encode('utf-8')).hexdigest()[:10]


def show_head(h, base):
    """`<repo>@<branch> <sha>` with the repository shown as show() shows a path; the project itself by its name."""
    repo, at, rest = str(h).partition("@")
    r = show(repo, base)
    return (os.path.basename(repo) if r == "." else r) + at + rest


def show(p, base):
    """A path as a message shows it: relative to the session's project when it lies there (R2)."""
    b = norm(base) if base else ""
    if b and (p == b or p.startswith(b + "/")):
        return p[len(b) + 1:] or "."
    return p


def too_broad(p, home):
    """A path no warning is raised for: the store itself or a folder above it, a repository's top folder, or a
    drive. A note that names one of those names everything in it, which is no conflict with any one file. A path on
    a drive this machine does not have is no conflict either."""
    if not drive_ok(p):
        return True
    h = norm(home)
    if covers(p, h) or re.fullmatch(r"[a-z]:", p or "", re.I):
        return True
    return bool(repo_of(p) == p and os.path.isdir(p))


def scratch(home, sid, f):
    """A file in the session's own scratch folder, temportal/tmp/<session>: never a conflict (the false positive
    of 2026-11-12, a note naming the store warned of a session's own scratch files)."""
    t = norm(os.path.join(home, "temportal", "tmp"))
    return covers(t, f)


def rebase(home, sid, room, fair_cut):
    """(the text a session is given at this message, its session.json changed). '' when nothing changed."""
    path = os.path.join(_dir(home, sid), "session.json")
    s = _read_json(path)
    if not s:
        return "", False
    base = s.get("cwd") or ""
    if s.get("stale"):
        st = s["stale"]
        if st.get("told"):
            return "", False
        st["told"] = True
        s["anchorSeen"] = max(int(s.get("anchorSeen") or 0), int(st.get("anchorVersion") or 0))
        _write_json(path, s)
        return (f"phi (p4-phi): this session's work is superseded and it is stale in the session tree: "
                f"\"{st.get('note')}\". Re-base onto that before going on; the session that started it was told "
                f"to archive it, and its outcome is kept there."), True
    warnings = [w["text"] for w in s.get("relayPending") or [] if isinstance(w, dict)]
    told = s.setdefault("relayWarned", [])
    told.extend(w["key"] for w in s.get("relayPending") or [] if isinstance(w, dict) and w.get("key") not in told)
    s["relayPending"] = []
    parent = _parent(s)
    anchor = _read_json(anchor_path(home, parent))
    if "anchorSeen" not in s:                     # RF1: the first look takes what is there as seen, relays none of it
        s["anchorSeen"] = int(anchor.get("version") or 0)
        s["marksGiven"] = mark_keys(home, parent)
    seen = int(s.get("anchorSeen") or 0)
    given = s.setdefault("marksGiven", [])
    version = int(anchor.get("version") or 0)
    fresh = version > seen
    marks, others = [], []
    if fresh:
        changed = anchor.get("changedAt") or {}
        nodes = sorted((anchor.get("nodes") or {}).items())
        par = anchor.get("parent") or {}
        for nid, n in nodes + [(parent, par)]:
            if nid == sid or int(changed.get(nid) or 0) <= seen:
                continue
            for m in n.get("marks") or []:
                key = mark_key(nid, m)                 # each mark relayed once, however often its node changes (R4)
                if key not in given:
                    given.append(key)
                    marks.append((nid, n.get("title") or nid, m))
            if nid == parent:
                continue
            bits = []
            if n.get("heads"):
                bits.append("heads " + ", ".join(show_head(h, base) for h in n["heads"]))
            if n.get("files"):
                bits.append(f"{len(n['files'])} file(s) changed: " + ", ".join(show(f, base) for f in n["files"][:12])
                            + (" ..." if len(n["files"]) > 12 else ""))
            mark = hashlib.sha1(json.dumps([n.get("heads"), n.get("files")]).encode()).hexdigest()[:10]
            if bits and (s.setdefault("othersGiven", {}).get(nid) != mark):
                s["othersGiven"][nid] = mark
                others.append(f"- \"{n.get('title') or nid}\" ({nid}): " + "; ".join(bits))
        s["anchorSeen"] = version
        del given[:-400]                               # the newest keys are enough to tell a mark already given
        if s.get("forked") and shard_of(s):          # a fork keeps its own agenda: only what touches its shard
            own = shard_of(s)
            marks = [x for x in marks if any(overlap(p, o) for p in x[2].get("paths") or [] for o in own)]
            others = [line for line in others if any(show(o, base) in line for o in own)]
    # the direct warnings: uncommitted files and shard paths against what is deprecated, and against other shards
    mine = [f for f in uncommitted(edited_files(home, sid)) if not scratch(home, sid, f)]
    shard = shard_of(s)
    every_mark = [(nid, n.get("title") or nid, m) for nid, n in (anchor.get("nodes") or {}).items() if nid != sid
                  for m in n.get("marks") or []]
    every_mark += [(parent, (anchor.get("parent") or {}).get("title") or parent, m)
                   for m in (anchor.get("parent") or {}).get("marks") or []]
    for nid, title, m in every_mark:
        for p in m.get("paths") or []:
            if too_broad(p, home):
                continue
            hit = sorted({f for f in mine if covers(p, f) or covers(f, p)} | {x for x in shard if overlap(x, p)})
            key = f"mark:{nid}:{m.get('time')}:{p}"
            if hit and key not in told:
                told.append(key)
                warnings.append(f"\"{title}\" wrote \"{_short(m.get('claim'), 300)}\", which names {show(p, base)}; "
                                f"this session has {', '.join(show(h, base) for h in hit[:5])} there. Stop that work "
                                f"and message {nid} by SendMessage before going on.")
    for nid, n in (anchor.get("nodes") or {}).items():
        if nid == sid:
            continue
        for pat in n.get("shard") or []:
            hit = sorted({f for f in mine if covers(pat, f)})
            key = f"shard-edit:{nid}:{pat}:{','.join(hit)}"
            if hit and key not in told:
                told.append(key)
                warnings.append(f"this session has uncommitted changes to {', '.join(show(h, base) for h in hit[:5])}, "
                                f"inside the shard of \"{n.get('title') or nid}\", {show(pat, base)}. Stop that work "
                                f"and message {nid} by SendMessage; that session alone changes it.")
    if not (warnings or marks or others):
        _write_json(path, s)
        return "", fresh
    parts = []
    if warnings:
        parts.append("phi (p4-phi): stop before any tool runs. " + " ".join(f"({k + 1}) {w}" for k, w in
                                                                          enumerate(warnings)))
    if marks:
        parts.append(f"phi (p4-phi): what the sessions beside this one deprecated or replaced since it last looked "
                     f"(anchor v{version}), in full:\n" + "\n".join(
                         f"- \"{t}\" ({nid}): {m.get('claim')} (source: {m.get('source')})" for nid, t, m in marks))
    if others:
        left = max(0, room - sum(len(p) for p in parts) - 200)
        cut = fair_cut(others, left) if left else []
        if cut:
            parts.append("phi (p4-phi): what else changed beside this session since it last looked:\n" + "\n".join(cut))
    _write_json(path, s)
    return "\n\n".join(parts), True


def _short(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 4] + " ..."


# --- routing ---------------------------------------------------------------------------------------------------------

def names_nothing(p, home, base=""):
    """True when a path names no one shard or scope: the project's root, the store, a folder above either, or a
    drive's root. A brief that names the project names everything in it, so it is no route and no fork's share (
    ezexe's acceptance check of 2026-11-12: the project root routed a brief falsely and advised fork six times)."""
    p = norm(p)
    if not p or p == "/" or re.fullmatch(r"[a-z]:/?", p, re.I):
        return True
    h = norm(home) if home else ""
    roots = [x for x in (h, norm(os.path.dirname(os.path.dirname(h))) if h else "", norm(base) if base else "") if x]
    return any(covers(p, r) for r in roots)


def owners(home, sid, text, base):
    """[(sessionId, title, pattern)] of the other live sessions whose shard holds a path the message names, the
    deepest shard first: those are the nodes the message belongs to. An archived or retired session owns nothing,
    and a path naming the whole project names no shard."""
    named = [n for n in paths_in(text, base) if not names_nothing(n, home, base)]
    if not named:
        return []
    every = _sessions(home)
    me = every.get(sid, {})
    above = set()
    p = _parent(me)
    while p and p not in above:
        above.add(p)
        p = _parent(every.get(p, {}))
    below, grow = set(), {sid}                    # a parent's shard covers its children's: never routed down
    while grow:
        grow = {k for k, v in every.items() if _parent(v) in grow and k not in below and k != sid}
        below |= grow
    out = []
    for oid, s in every.items():
        if oid == sid or oid in above or oid in below or gone(home, s):
            continue
        for pat in shard_of(s):
            if names_nothing(pat, home, base):
                continue
            if any(covers(pat, n) or covers(n, pat) for n in named):
                out.append((oid, _title(s), pat))
                break
    return sorted(out, key=lambda x: -len(_root(x[2])))


def route_text(home, sid, text, base):
    got = owners(home, sid, text, base)
    if not got:
        return ""
    oid, title, pat = got[0]
    return (f"phi (p4-phi): this message names {pat}, which is the shard of \"{title}\" ({oid}). Send it there with "
            f"SendMessage (`to`: {oid}) instead of working on it here or starting a new session for it.")


def shards_line(home, sid):
    """The other sessions' shards in a few words, for the standing instruction; '' when none declared one."""
    every = _sessions(home)
    out = [f"\"{_title(s)}\" ({oid}): {', '.join(shard_of(s)[:3])}" for oid, s in sorted(every.items())
           if oid != sid and shard_of(s) and not gone(home, s)]
    return "; ".join(out[:6])


# --- fork or fresh -----------------------------------------------------------------------------------------------------
#
# Measured 2026-11-12 on this machine's app records, 84 children with a parent transcript on disk: the parent's
# transcript held a median 2.9 MB when a fork started (quartiles 1.9 and 4.4 MB) and 2.1 MB when a fresh session
# did. Above 1 MB a parent had a median of 2 to 27 of ezexe's turns behind it, and already held 0.76 to 0.86 of
# the brief's words: a fork there carries the rest of the parent's work into the child, while a brief carries most
# of what the child needs. Under 1 MB, 17 of 22 children were fresh and the parent held little. So a fork is advised
# only from a parent whose transcript is at most FORK_MAX_BYTES, for a child whose paths cover at least
# FORK_SHARE of the parent's scope; otherwise a fresh session.

FORK_MAX_BYTES = 1024 * 1024
FORK_SHARE = 0.5


def scope_of(home, sid):
    """What a session covers: its shard, else the files its latest delta and its children's anchor name."""
    s = _session(home, sid)
    if shard_of(s):
        return shard_of(s)
    files = set()
    for r in reversed(_rows(os.path.join(_dir(home, sid), "turns.jsonl"))):
        if isinstance(r.get("delta"), dict):
            files.update(r["delta"].get("files") or [])
            break
    for n in (_read_json(anchor_path(home, sid)).get("nodes") or {}).values():
        files.update(n.get("files") or [])
    return sorted(files)


def advise_start(home, parent, tool_input, transcript_bytes):
    """(what is advised, "fork" or "fresh", and why) for a start_session call from `parent`."""
    s = _session(home, parent)
    base = s.get("cwd") or ""
    brief = " ".join(str(tool_input.get(k) or "") for k in ("prompt", "background", "title"))
    child = [c for c in paths_in(brief, base) if not names_nothing(c, home, base)]
    scope = [p for p in scope_of(home, parent) if not names_nothing(p, home, base)]
    share = (sum(1 for p in scope if any(overlap(p, c) for c in child)) / len(scope)) if scope and child else 0.0
    short = transcript_bytes <= FORK_MAX_BYTES
    mb = transcript_bytes / (1024 * 1024)
    if short and share >= FORK_SHARE:
        return "fork", (f"the parent's transcript is {mb:.1f} MB, under {FORK_MAX_BYTES // (1024 * 1024)} MB, and the "
                        f"brief's paths cover {share:.0%} of the parent's scope: the child's work is the parent's")
    why = []
    if not short:
        why.append(f"the parent's transcript is {mb:.1f} MB, over {FORK_MAX_BYTES // (1024 * 1024)} MB: a fork "
                   f"would carry all of it into the child's context")
    if share < FORK_SHARE:
        why.append(f"the brief's paths cover {share:.0%} of the parent's scope" + ("" if child else
                                                                                    " (the brief names no path)"))
    return "fresh", "; ".join(why) + ". A fresh session given a brief and phi's slice of the anchor starts on its " \
                                      "own task alone"


def pin_text(s):
    """The line that keeps a forked child on its own agenda, above the conversation it inherited."""
    task = _short(s.get("task") or "", 300)
    if not task:
        return ""
    shard = shard_of(s)
    return (f"phi (p4-phi): this session is a fork; the conversation above its first message is the parent's and "
            f"is background, not its agenda. Its own task: \"{task}\""
            + (f"; its shard: {', '.join(shard[:5])}." if shard else ". It has declared no shard yet: "
               f"`phi.py shard <paths>` names what it alone changes."))


def slice_text(home, s):
    """A fresh child's start: what its parent's anchor holds for the child's paths, its shard or those its task
    names, and nothing else. One line when the parent has nothing for them."""
    parent = _parent(s)
    if not parent:
        return ""
    anchor = _read_json(anchor_path(home, parent))
    ps = _session(home, parent)
    base = s.get("cwd") or ps.get("cwd") or ""
    mine = shard_of(s) or paths_in(s.get("task") or "", base)
    ver = int(anchor.get("version") or 0)
    if not mine:
        return ""                                 # nothing to cut the anchor by: the background says the rest (P2)
    head = (f"phi (p4-phi): what the parent, \"{_title(ps)}\", has for this session's paths "
            f"({', '.join(show(p, base) for p in mine[:5])}), from its anchor v{ver}. Its task: \""
            f"{_short(ps.get('task') or '', 300)}\".")
    marks, heads, files = [], set(), []
    every = list((anchor.get("nodes") or {}).items()) + [(parent, anchor.get("parent") or {})]
    for nid, n in every:
        if nid == s.get("sessionId"):
            continue
        for m in n.get("marks") or []:
            if any(overlap(p, x) for p in m.get("paths") or [] for x in mine):
                marks.append(f"- \"{n.get('title') or nid}\": {m.get('claim')} (source: {m.get('source')})")
        touched = [f for f in n.get("files") or [] if any(covers(x, f) for x in mine)]
        if touched:
            files.append(f"- \"{n.get('title') or nid}\" changed {', '.join(touched[:8])}")
            heads.update(n.get("heads") or [])
    notes = [f"- {_short(r.get('claim'), 300)} (source: {_short(r.get('source'), 120)})"
             for r in _rows(os.path.join(_dir(home, parent), "notes.jsonl"))
             if not str(r.get("claim") or "").lower().startswith(MARKS)
             and any(overlap(p, x) for p in paths_in(r.get("claim"), base) for x in mine)]
    if not (marks or files or notes):
        return head + " It has nothing for them yet."
    out = [head]
    if marks:
        out += ["Deprecated or replaced there, in full:"] + marks
    if notes:
        out += ["Notes about them:"] + notes
    if files:
        out += ["Changed there:"] + files + (["Heads to build on: " + ", ".join(sorted(heads))] if heads else [])
    return "\n".join(out)


def scratch_line(home, cli, base):
    """P9: the folder a started session keeps its temporary files in, named at its start so it never asks or guesses."""
    if not cli:
        return ""
    return (f"phi (p4-phi): this session's scratch folder is {show(norm(os.path.join(home, 'temportal', 'tmp', cli)), base)}/"
            f": temporary files go there, and are named by that path.")


def anchor_version(home, parent):
    return int(_read_json(anchor_path(home, parent)).get("version") or 0) if parent else 0


def mark_keys(home, parent):
    """The keys of every mark the parent's anchor holds: what a child's start already carries."""
    a = _read_json(anchor_path(home, parent)) if parent else {}
    nodes = list((a.get("nodes") or {}).items()) + [(parent, a.get("parent") or {})]
    return [mark_key(nid, m) for nid, n in nodes for m in n.get("marks") or []]


def child_paths(home, s):
    """The paths a child's start is cut to: its shard, else those its task names; [] when neither names any."""
    base = s.get("cwd") or _session(home, _parent(s)).get("cwd") or ""
    return shard_of(s) or paths_in(s.get("task") or "", base)


# --- phi/ tracked in the store -------------------------------------------------------------------------------------------
#
# The session tree reaches the other machines through the store's git, like the rest of it: session.json, turns.jsonl,
# notes.jsonl, reports.jsonl, plan.json and anchor.json are tracked; what is per machine or made again from them is
# ignored. The ignore lines are made sure of here, before anything is added, since the recall hook that seeds the
# rest of .gitignore runs beside this one at a start.

IGNORED = ("phi/sessions/*/log.jsonl", "phi/sessions/*/session.md", "phi/sessions.md", "phi/rules.md",
           "phi/catchup.json", "phi/**/*.tmp", "phi/sessions/*/.calls/", "phi/.agents/", "phi/.nudge/")
TRACKED_MARK = "p4-phi-tracked"


FILTER_ATTR = "phi/** filter=p4path"


def _path_filter(home):
    """The store's git runs pathfilter.py on phi/ (PL1): set in this machine's git config, which names this machine's
    python and plugin, and in .gitattributes, which every machine shares. True when .gitattributes changed."""
    py = sys.executable.replace("\\", "/")
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pathfilter.py").replace("\\", "/")
    for kind in ("clean", "smudge"):
        want = f'"{py}" -I "{script}" {kind}'
        have = _git(home, "config", "--local", "--get", f"filter.p4path.{kind}")
        if not have or have.stdout.strip() != want:
            _git(home, "config", "--local", f"filter.p4path.{kind}", want)
    ga = os.path.join(home, ".gitattributes")
    try:
        with open(ga, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    if FILTER_ATTR in {x.strip() for x in text.splitlines()}:
        return False
    with open(ga, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if not text or text.endswith("\n") else "\n") + "# the project's root as {project} in git (p4-phi)\n"
                + FILTER_ATTR + "\n")
    return True


def _ignore_lines(home):
    gi = os.path.join(home, ".gitignore")
    try:
        with open(gi, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    have = {x.strip() for x in text.splitlines()}
    missing = [x for x in IGNORED if x not in have]
    if missing:
        with open(gi, "a", encoding="utf-8", newline="\n") as f:
            f.write(("" if not text or text.endswith("\n") else "\n") + "# the session tree's per-machine and made-again "
                    "files (p4-phi)\n" + "".join(x + "\n" for x in missing))
    return bool(missing)


def track(home, first_only=False):
    """Stage phi/ in the store's git; the first time, commit it on its own. Returns True when it committed. Only
    when the store's p4.json sets phi.track. The project's root goes into git as {project} through the store's
    path filter (PL1), so another machine's checkout names its own files."""
    try:
        import p4conf
        if not (p4conf.section(home, "phi", write=False) or {}).get("track"):
            return False
    except Exception:  # noqa: BLE001
        return False
    top = _git(home, "rev-parse", "--show-toplevel")
    if not top or top.returncode != 0 or norm(top.stdout.strip()) != norm(home):
        return False
    gd = _git(home, "rev-parse", "--absolute-git-dir")
    mark = os.path.join(gd.stdout.strip(), TRACKED_MARK) if gd and gd.returncode == 0 else ""
    first = bool(mark) and not os.path.exists(mark)
    if first_only and not first:
        return False
    changed = _ignore_lines(home)
    attrs = _path_filter(home)
    _git(home, "add", "-A", "--", "phi", *([".gitignore"] if changed else []), *([".gitattributes"] if attrs else []))
    if not first:
        return False
    paths = ["phi"] + ([".gitignore"] if changed else []) + ([".gitattributes"] if attrs else [])
    staged = _git(home, "diff", "--cached", "--name-only", "--", *paths)
    if staged and staged.stdout.strip():
        _git(home, "-c", "user.name=p4", "-c", "user.email=p4@localhost", "commit", "-q", "--no-verify", "-m",
             "phi: the session tree, tracked", "--", *paths)
    try:
        with open(mark, "w", encoding="utf-8") as f:
            f.write("tracked\n")
    except OSError:
        pass
    return True


# --- a shared home store -----------------------------------------------------------------------------------------------
#
# Related repositories can share one session tree: a project's p4.json names `phi.home`, the home store's git remote
# (not a path, so it holds on every machine). Each machine resolves remotes to its own store folders through a map kept
# per user, beside Claude Code's settings and in no repository: p4-stores.json, written at every start for the store
# that started. The project's session tree goes to the home's phi/; its memory, rules and recall data stay its own.

def stores_map_path():
    return os.environ.get("P4_PHI_STORES") or os.path.join(
        os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"), "p4-stores.json")


def remote_key(url):
    """A git remote in one form: host/owner/name, whatever the scheme, user or .git suffix."""
    u = str(url or "").strip().lower()
    u = re.sub(r"^[a-z+]+://", "", u)
    u = re.sub(r"^[^@/]+@", "", u)
    u = u.replace(":", "/", 1) if re.match(r"^[^/]+:[^/]", u) else u
    return re.sub(r"\.git$", "", u.rstrip("/"))


def remote_of(store):
    r = _git(store, "remote", "get-url", "origin")
    return remote_key(r.stdout.strip()) if r and r.returncode == 0 and r.stdout.strip() else ""


def remember_store(store):
    """Keep this machine's folder for the store's remote in the per-user map, only for a store whose p4.json names a
    home (the home names itself): no file outside a repository for anyone who never set one. Quiet on any failure."""
    try:
        import p4conf
        if not (p4conf.section(store, "phi", write=False) or {}).get("home"):
            return
    except Exception:  # noqa: BLE001
        return
    key = remote_of(store) if store and os.path.isdir(store) else ""
    if not key:
        return
    path = stores_map_path()
    m = _read_json(path)
    if m.get(key) == store:
        return
    m[key] = store
    try:
        _write_json(path, m)
    except OSError:
        pass


def tree_home(store):
    """(where the session tree of `store`'s project lives, the remote named but not found here or '')."""
    if not store:
        return store, ""
    try:
        import p4conf
        named = (p4conf.section(store, "phi", write=False) or {}).get("home")
    except Exception:  # noqa: BLE001
        named = None
    if not named:
        return store, ""
    key = remote_key(named)
    if key == remote_of(store):
        return store, ""
    found = _read_json(stores_map_path()).get(key) or ""
    if found and os.path.isdir(found):
        return found, ""
    return store, str(named)


# --- stale nodes ---------------------------------------------------------------------------------------------------------
#
# A finished child whose work a newer note supersedes holds a picture of the tree that is no longer true. Relayed to, or
# relayed from, it can only push the others back to that picture: ezexe's "uncertainty loop", met when a migration
# session's recall/ plus temportal/ store was superseded by the fold into phi/. So it is fenced off at once: its
# still-true outcome kept as one note on its parent, it left out of the anchor, the slices and the relay, and the parent
# told to archive it. A stale child that is messaged again is handed what superseded it, and is un-staled only when its
# next turn ends having seen that anchor.

def finished(home, sid):
    """True when a session's work is over: its last turn was shown done or its plan has steps and none still open,
    and nothing it changed is left uncommitted. A session with no plan and no done turn is never taken as finished."""
    import plans
    turns = _rows(os.path.join(_dir(home, sid), "turns.jsonl"))
    if not turns:
        return False
    steps = plans.load(home, sid).get("steps") or []
    over = bool(turns[-1].get("done")) or (bool(steps) and all(x.get("status") == "completed" for x in steps))
    return over and not uncommitted(edited_files(home, sid))


def superseded(home, sid, s, others_marks):
    """The newer note that supersedes a finished session's work: one naming a file of its last delta or its shard,
    or sharing words with its root step. None when there is none."""
    import plans
    turns = _rows(os.path.join(_dir(home, sid), "turns.jsonl"))
    last = turns[-1] if turns else {}
    since = str(last.get("time") or "")
    files = (last.get("delta") or {}).get("files") or []
    shard = shard_of(s)
    root = str(s.get("rootStep") or "")
    root_text = ""
    if root and _parent(s):
        st = plans.step_of(plans.load(home, _parent(s)), root)
        root_text = (st or {}).get("content", "") or plans.load(home, sid).get("rootText", "")
    for nid, title, m in others_marks:
        if str(m.get("time") or "") < since:
            continue
        if s.get("unstaled") and str(m.get("time") or "") <= str(s.get("unstaled")):
            continue                                  # it re-based onto this note already
        hits = [p for p in m.get("paths") or [] if not too_broad(p, home)
                and (any(covers(p, f) or covers(f, p) for f in files) or any(overlap(p, x) for x in shard))]
        if hits or (root_text and plans.bears(m.get("claim"), root_text)):
            return nid, title, m
    return None


def retire(home, parent, sid, s, by, version, now):
    """Mark a session stale and keep its still-true outcome as one replaces: note on its parent."""
    nid, title, m = by
    turns = _rows(os.path.join(_dir(home, sid), "turns.jsonl"))
    last = turns[-1] if turns else {}
    d = last.get("delta") or {}
    base = s.get("cwd") or ""
    left = ", ".join(show(f, base) for f in (d.get("files") or [])[:8]) or "no file changes"
    heads = ", ".join(show_head(h, base) for h in d.get("heads") or []) or "no heads"
    claim = (f"replaces: \"{_title(s)}\" ({sid}) as a live node. What it left in place stays true: {left}, at "
             f"{heads}. " + findings_of(last) + " Its picture of the tree is "
             f"superseded by \"{title}\": \"{_short(m.get('claim'), 300)}\".")
    row = {"time": now, "claim": claim[:FINDINGS_CHARS + 1600], "source": f"phi stale-node retirement, anchor v{version}",
           "kind": "decision", "cliSessionId": ""}
    path = os.path.join(_dir(home, parent), "notes.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    spath = os.path.join(_dir(home, sid), "session.json")
    disk = _read_json(spath)
    disk["stale"] = {"anchorVersion": version, "by": nid, "note": _short(m.get("claim"), 300), "time": now}
    _write_json(spath, disk)
    _pend_archive(home, parent, sid, s, "stale")


class locked:
    """A lock file beside `path`, held while a read-modify-write of it runs. Waits up to LOCK_WAIT_S, and takes over
    a lock older than LOCK_STALE_S, so a crashed hook never blocks the next one."""

    def __init__(self, path):
        self.lock = path + ".lock"
        self.held = False

    def __enter__(self):
        import time
        os.makedirs(os.path.dirname(self.lock), exist_ok=True)
        end = time.time() + LOCK_WAIT_S
        while True:
            try:
                os.close(os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                self.held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.lock) > LOCK_STALE_S:
                        os.remove(self.lock)
                        continue
                except OSError:
                    continue
                if time.time() > end:
                    return self                   # never block a hook for good: go on unlocked
                time.sleep(0.02)
            except OSError:
                return self

    def __exit__(self, *exc):
        if self.held:
            try:
                os.remove(self.lock)
            except OSError:
                pass
        return False


LOCK_WAIT_S = 3.0
LOCK_STALE_S = 10.0


def _pend_archive(home, parent, sid, s, kind):
    """The parent's next message names this child to archive (stale_text). Under a lock: two children retired at
    the same minute each read-modify-wrote the parent's session.json, and the later write lost the earlier child,
    so the parent was never told to archive it (check 6, 2026-11-12)."""
    ppath = os.path.join(_dir(home, parent), "session.json")
    with locked(ppath) as lk:
        if not lk.held:                           # never written unlocked: kept on a file of its own, read later
            _write_json(os.path.join(_dir(home, parent), f"archive-pending-{_safe(sid)}.json"),
                        {"id": sid, "title": _title(s), "kind": kind})
            return
        pd = _read_json(ppath)
        if pd:
            pend = pd.setdefault("staleChildren", [])
            pend[:] = [x for x in pend if not (isinstance(x, dict) and x.get("id") == sid)]
            pend.append({"id": sid, "title": _title(s), "kind": kind})
            pd["staleTold"] = [x for x in pd.get("staleTold") or [] if x != sid]
            _write_json(ppath, pd)


def _safe(sid):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(sid or ""))[:80]


def drain_archive(home, parent):
    """The children a locked write could not name on the parent, from their own files; the files are removed."""
    out = []
    for p in glob.glob(os.path.join(_dir(home, parent), "archive-pending-*.json")):
        d = _read_json(p)
        if isinstance(d, dict) and d.get("id"):
            out.append({"id": d["id"], "title": d.get("title") or d["id"], "kind": d.get("kind") or "done"})
        try:
            os.remove(p)
        except OSError:
            pass
    return out


DISPOSABLE = re.compile(r"\barchive(?:d)?\s+(?:it\s+|this session\s+)?when\s+(?:it(?:'s| is)\s+|you(?:'re| are)\s+)?"
                        r"(?:done|finished)\b", re.I)


def commits_between(repo, old, new):
    """The one-line subjects of the commits from `old` to `new` in a repository, newest first, at most 8."""
    if not old or not new or old == new:
        return []
    r = _git(repo, "log", "--format=%h %s", "-8", f"{old}..{new}")
    return [x.strip() for x in r.stdout.splitlines() if x.strip()] if r and r.returncode == 0 else []


def outcome(home, sid, s):
    """What a finished session leaves: (files changed, heads with the commits made since its first turn, what is
    still open)."""
    import plans
    turns = _rows(os.path.join(_dir(home, sid), "turns.jsonl"))
    base = s.get("cwd") or ""
    files = edited_files(home, sid)
    first, last = {}, {}
    for r in turns:
        for h in (r.get("delta") or {}).get("heads") or []:
            repo, _, sha = str(h).rpartition(" ")
            first.setdefault(repo, sha)
            last[repo] = sha
    heads_, commits = [], []
    for repo, sha in last.items():
        heads_.append(show_head(f"{repo} {sha}", base))
        commits += commits_between(repo.rsplit("@", 1)[0], first.get(repo), sha)
    p = plans.load(home, sid)
    still = [f"step {x['addr']} \"{_short(x.get('content'), 80)}\" {x.get('status') or 'pending'}"
             for x in p.get("steps") or [] if x.get("status") != "completed"]
    still += [f"task {t.get('id')} ({_short(t.get('what'), 60)}) open" for _, t in plans._tasks(p)
              if t.get("status") == "open"]
    dirty = uncommitted(files)
    if dirty:
        still.append("uncommitted: " + ", ".join(show(f, base) for f in dirty[:8]))
    return files, heads_, commits, still


CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+((?:[\w.-]+/[\w.-]+)?#\d+)", re.I)


def closing_commits(home, sid, s):
    """[(repo, short sha, subject, [issues])] of the commits a session made since its first turn whose messages
    close an issue (`Closes #N`), oldest first."""
    turns = _rows(os.path.join(_dir(home, sid), "turns.jsonl"))
    first, last = {}, {}
    for r in turns:
        for h in (r.get("delta") or {}).get("heads") or []:
            repo, _, sha = str(h).rpartition(" ")
            first.setdefault(repo, sha)
            last[repo] = sha
    out = []
    for repo, sha in last.items():
        path = repo.rsplit("@", 1)[0]
        old = first.get(repo)
        made = str(s.get("createdAt") or "")
        # the first head is read at the first turn's end, so that turn's own commits are found by time
        early = _git(path, "log", "--reverse", f"--since={made}", "--format=%h%x1f%s%x1f%B%x1e", old) if made and old \
            else None
        late = _git(path, "log", "--reverse", "--format=%h%x1f%s%x1f%B%x1e", f"{old}..{sha}") if old and old != sha \
            else None
        text = "".join(r.stdout for r in (early, late) if r and r.returncode == 0)
        for rec in text.split("\x1e"):
            parts = rec.strip().split("\x1f")
            if len(parts) < 3:
                continue
            issues = list(dict.fromkeys(CLOSES.findall(parts[2])))
            if issues:
                out.append((path, parts[0], parts[1], issues))
    return out


def push_text(child_title, child, commits):
    """The top session's line: push and sync a finished child's issue-closing commits now, not ask."""
    named = "; ".join(f"{sha} \"{_short(subj, 80)}\" closes {', '.join(n)} in {repo}" for repo, sha, subj, n in commits)
    return (f"phi (p4-phi): \"{child_title}\" ({child}) finished with commits that close issues: {named}. "
            f"ezexe's rule is that green work closing an issue is pushed at once: once its suites pass, push that "
            f"repository's main and sync each p4 store it touches with `p4.py sync --push`, without asking ezexe, "
            f"and say in one line what was pushed. Asking stays for force-pushes, history rewrites and deletions.")


FINDINGS_CHARS = 3000          # of a retired child's final report, kept in its replaces: note
BARE = re.compile(r"^\W*(?:\w+\s+){0,4}(?:is\s+)?(?:done|finished|complete[d]?)(?:\s+and\s+reported)?\W*$", re.I)


def findings_of(last):
    """A retired child's findings from its final turn: the shown-done line, and its report in full up to
    FINDINGS_CHARS, from the turn's earlier messages when the last one only says it is done. Says so when the turn
    left none; never a bare "done"."""
    done = " ".join(str(last.get("done") or "").split())
    report = str(last.get("report") or "").strip()
    said = str(last.get("said") or "").strip()
    if said and (not report or len(report) < 400 or BARE.match(report)):
        report = said
    if BARE.match(report or ""):
        report = ""
    out = f"Shown done: \"{_short(done, 400)}\". " if done and not BARE.match(done) else ""
    if report:
        # #34: a report leads with its result, so the head is kept and the tail cut
        cut = report if len(report) <= FINDINGS_CHARS else report[:FINDINGS_CHARS - 3].rstrip() + "..."
        return out + f"Its findings, from its final report: \"{cut}\"."
    return out + "Its final turn left no report text with findings: read its transcript before relying on it."


def retire_done(home, parent, sid, s, now, extra=""):
    """A disposable child whose work is over: its outcome kept as one replaces: note on its parent, it left out of
    the relay, the anchors and the down-lines, and the parent told at its next message to archive it. Returns True
    when it was retired now."""
    path = os.path.join(_dir(home, sid), "session.json")
    disk = _read_json(path)
    if not parent or not disk or disk.get("doneRetired"):
        return False
    files, heads_, commits, still = outcome(home, sid, disk)
    base = disk.get("cwd") or ""
    turns = _rows(os.path.join(_dir(home, sid), "turns.jsonl"))
    last = turns[-1] if turns else {}
    claim = (f"replaces: \"{_title(disk)}\" ({sid}) as a live node: it finished and was started to be archived "
             f"when done. " + (extra.strip() + " " if extra else "") + "Changed: " + (", ".join(show(f, base) for f in files[:10]) or "no files")
             + (" ..." if len(files) > 10 else "") + ". Heads: " + (", ".join(heads_) or "none") + ". Commits: "
             + ("; ".join(commits) or "none") + ". Still open: " + ("; ".join(still) or "nothing") + ". "
             + findings_of(last))
    row = {"time": now, "claim": claim[:FINDINGS_CHARS + 2000], "source": "phi archive-when-done retirement",
           "kind": "decision", "cliSessionId": ""}
    npath = os.path.join(_dir(home, parent), "notes.jsonl")
    os.makedirs(os.path.dirname(npath), exist_ok=True)
    with open(npath, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    disk["doneRetired"] = {"time": now}
    _write_json(path, disk)
    _pend_archive(home, parent, sid, disk, "done")
    return True


# --- merged worktrees named for removal (#22) ---------------------------------------------------------------------------
#
# Leftover checkouts under .claude/worktrees (one was 394 MB, mostly an ignored build tree) confused the top session
# and wasted disk. When a child is retired or archived, and at a top session's step boundary, the project's worktrees
# whose branch is already in the branch it came from, and that hold nothing else, are named for removal.

def worktrees(repo):
    """[(path, branch)] of a repository's linked worktrees, the main checkout left out."""
    r = _git(repo, "worktree", "list", "--porcelain")
    if not r or r.returncode != 0:
        return []
    out, cur = [], {}
    for line in r.stdout.splitlines() + [""]:
        if not line.strip():
            if cur.get("worktree"):
                out.append((cur["worktree"], cur.get("branch", "")))
            cur = {}
        elif line.startswith("worktree "):
            cur["worktree"] = line[9:].strip()
        elif line.startswith("branch "):
            cur["branch"] = line[7:].strip().removeprefix("refs/heads/")
    return out[1:]


def _open_pr(repo, branch):
    import shutil
    if not shutil.which("gh"):
        return False
    try:
        r = subprocess.run(["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number", "-q", "length"],
                           cwd=repo, capture_output=True, text=True, timeout=GIT_S)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() not in ("", "0")


def merged_worktrees(repo):
    """(those to remove: [(path, branch, base)], those kept: [(path, reason)]) of a repository's worktrees. One is
    removed when its branch is an ancestor of the main checkout's branch or of the default branch, and it holds no
    uncommitted, untracked or stashed work, no commit its upstream lacks and no open pull request."""
    if not repo:
        return [], []
    head = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    bases = [head.stdout.strip()] if head and head.returncode == 0 else []
    d = _git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if d and d.returncode == 0 and d.stdout.strip():
        bases.append(d.stdout.strip())
    stashes = _git(repo, "stash", "list")
    stash_text = stashes.stdout if stashes and stashes.returncode == 0 else ""
    gone, kept = [], []
    for path, branch in worktrees(repo):
        if not branch:
            kept.append((path, "a detached checkout, no branch to judge"))
            continue
        base = next((b for b in bases if b and b != branch and b != "HEAD" and
                     (_git(repo, "merge-base", "--is-ancestor", branch, b) or subprocess.CompletedProcess([], 1))
                     .returncode == 0), "")
        if not base:
            kept.append((path, f"{branch} is not merged"))
            continue
        st = _git(path, "status", "--porcelain")
        if st is None or st.returncode != 0:
            kept.append((path, "its status could not be read"))
            continue
        if st.stdout.strip():
            kept.append((path, "uncommitted or untracked files"))
            continue
        if re.search(rf"(?m)^stash@\{{\d+\}}: (?:WIP on|On) {re.escape(branch)}:", stash_text):
            kept.append((path, "a stash on its branch"))
            continue
        up = _git(repo, "rev-list", "--count", f"{branch}@{{u}}..{branch}")
        if up and up.returncode == 0 and up.stdout.strip() not in ("", "0"):
            kept.append((path, "commits its upstream lacks"))
            continue
        if up and up.returncode == 0 and _open_pr(repo, branch):
            kept.append((path, "an open pull request"))
            continue
        gone.append((path, branch, base))
    return gone, kept


def worktrees_text(home, sid, repo):
    """The top session's line naming the merged worktrees to remove and the ones kept with why, said once per set;
    '' when there is nothing new to say."""
    gone, kept = merged_worktrees(repo)
    if not gone:
        return ""
    path = os.path.join(_dir(home, sid), "session.json")
    disk = _read_json(path)
    told = [x for x in disk.get("worktreesTold") or [] if isinstance(x, str)]
    keys = [f"{p}|{b}" for p, b, _ in gone]
    if disk and all(k in told for k in keys):
        return ""
    if disk:
        disk["worktreesTold"] = (told + [k for k in keys if k not in told])[-100:]
        _write_json(path, disk)
    rm = "; ".join(f"`git worktree remove \"{p}\"` then `git branch -d {b}` (in {b0})" for p, b, b0 in gone)
    keep = "; ".join(f"{p} ({why})" for p, why in kept)
    return (f"phi (p4-phi): worktrees whose branch is merged and that hold nothing else, so remove them now: {rm}."
            + (f" Kept: {keep}." if keep else ""))


def stale_text(pend):
    """The parent's one line about the children in `pend` to archive, stale or done; '' for none."""
    pend = [x for x in pend or [] if isinstance(x, dict)]
    if not pend:
        return ""
    out = []
    done = [x for x in pend if x.get("kind") == "done"]
    stale = [x for x in pend if x.get("kind") != "done"]
    if stale:
        names = ", ".join(f"\"{x.get('title')}\" ({x.get('id')})" for x in stale)
        out.append(f"phi (p4-phi): stale, their work superseded by a newer note, their outcome kept as a replaces: "
                   f"note on this session: {names}. Archive them now with `mcp__ccd_session_mgmt__archive_session`.")
    if done:
        names = ", ".join(f"\"{x.get('title')}\" ({x.get('id')})" for x in done)
        out.append(f"phi (p4-phi): finished, started to be archived when done, their outcome kept as a replaces: "
                   f"note on this session: {names}. Archive them now with `mcp__ccd_session_mgmt__archive_session`.")
    return "\n".join(out)
