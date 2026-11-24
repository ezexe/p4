"""relay.py: what keeps the linked sessions of one session tree in step while they work, and what p4-phi does with a
session whose work is over.

The functions that read the store take its home and session ids. phi.py calls them from its hooks and commands, and
plans.py, issues.py, puppeteer.py, controls.py, starts.py and gaps.py call them too.

  owned paths  what a session alone may change: paths or globs, set by `phi.py shard <paths>` and kept in its
          session.json as `shard`. The address book lists them and routes a message by them, as book.py says, and a
          start's advice and a puppeteer's routing read them as a session's scope. No session is held against
          another's: each session works in the one checkout, on the paths it holds, as phi.py keeps them apart.
  delta   a turn's change, kept on its row in turns.jsonl at Stop: the branch heads of the repositories it edited
          in, the files it changed, and its `deprecates:` and `replaces:` notes written since its last turn, with
          the paths they name. The heads and files are the session's own record, which its outcome, its closing
          commits and the push line read.
  anchor  <parent's folder>/anchor.json: each child's marked notes, owned paths, task list and parent step, and the
          parent's own marked notes, owned paths and task list, under a version that goes up when any of that
          changes. It holds no heads and no files: another session's lie in another worktree, nothing to build on
          before the tree's orchestrator merges its branch. The orchestrators share phi/anchor.json. It is made
          again at Stop, at `phi.py shard`, at each update_plan call and when a subagent is bound.
  route   a message that names a path inside another session's owned paths belongs to that session: the session is
          told to send it there with SendMessage. The address book finds the owner, as book.holders says.
  rebase  at every message a session is given, including the app's side-session events: first the warnings other
          code kept for it with relay.warn, each once. Then, when its parent's anchor is newer than the version it
          last saw, the other sessions' deprecations and replacements whose words touch its task or open steps, in
          full, the rest by count and the pages that hold them, cut to the room phi.py gives this text. A first look
          takes what is there as seen. Nothing when nothing changed.

The rest of the module keeps phi/ in the store's git, maps a shared store's remote to this machine's folder, advises
fork or fresh for a start, cuts a title at a clause, fences off a finished child whose work a newer note supersedes,
counts a finished child as archived with its outcome kept as a note on its parent, and offers a done
orchestrator's finished sessions to ezexe to archive.
"""

import glob
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:                   # run by itself with -I, as for the tree's first commit, it finds its own
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402  the reader that waits out another process's replace of a file

MARKS = ("deprecates:", "replaces:")
PATH_RE = re.compile(r"`([^`\s]+)`|((?:[A-Za-z]:)?[\w.~-]*[\\/][\w.\\/*~-]+)")
GIT_S = 5                        # what one git call may take inside a hook
TRACK_HOOK_S = 6                 # all of relay.track's git calls inside a hook: SessionStart has 20 s, Stop 30 s, and
                                 # the self-archive check before its call 10 s
TRACK_S = 300                    # one git call of the tree's first commit, run in a process of its own outside the
                                 # hooks: the path filter runs a python per file of the tree


# --- files ---------------------------------------------------------------------------------------------------------

def _read_json(path):
    """The JSON object at `path`, {} where there is none. A file another process is replacing is waited out, by
    p4conf.load_json, so a record that is there never reads as no record for the length of a move."""
    d, _ = p4conf.load_json(path)
    return d if isinstance(d, dict) else {}


_HOLDS = threading.local()     # the paths whose lock this thread holds
_GAVE_UP = {}                  # a lock file -> when this process stopped waiting for it


def _held(path):
    """True while this thread holds `path`'s lock, taken with relay.locked."""
    return path in getattr(_HOLDS, "paths", ())


def _write_json(path, d):
    """`d` written to `path`. A session's record is written under its lock, and with the warnings that wait on
    disk, not the copy the caller read earlier: only relay.warn and relay.take_warnings change `relayPending`,
    under the lock, so no other read-modify-write of the record can drop a warning written meanwhile."""
    if os.path.basename(path) == "session.json" and not _held(path):
        with locked(path):                        # not got: the entries are read again right before the write
            keep_pending(path, d)
            _write_raw(path, d)
        return
    _write_raw(path, d)


def keep_pending(path, d):
    """`d` given the warnings and the told keys the record on disk holds now. For a writer that did not take them
    under the lock."""
    fresh = _read_json(path)
    if "relayPending" in fresh:
        d["relayPending"] = fresh["relayPending"]
    if isinstance(fresh.get("relayWarned"), list):
        mine = d.get("relayWarned") if isinstance(d.get("relayWarned"), list) else []
        d["relayWarned"] = mine + [k for k in fresh["relayWarned"] if k not in mine]
    return d


def _write_raw(path, d):
    """The record `d` written to `path` by the kit's one writer, which waits out a reader that takes no lock and
    has `path` open, for REPLACE_WAIT_S."""
    p4conf.write_whole(path, json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True) + "\n", wait=REPLACE_WAIT_S)


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


# --- a node's folder: the folder each started session, terminal worker and reading team gets -----------------------
#
# ezexe, 2026-11-24: "drop expanding into '.claude/p4/.claude/p4/.....' write the nested tree directly into phi/". A
# node is a folder of <root>/phi/tree, nested by parent: <root>/phi/tree/<ancestor ids...>/<id>, holding its
# node.json and every file the node has: a session node's folder is its session folder (session.json, turns.jsonl,
# drafts/), a worker's holds its brief, start, resume, settings, log and report. The home every function is handed
# stays the tree's root store; a node is found from its id, never from the folder a session runs in, since a session
# started inside a nested folder waits at Claude Code's trust question for every new folder.

NODE = "node.json"               # <node folder>/node.json: {id, kind, parent, place, sections, time} of a node
NODE_PATH_MAX = 180              # the longest folder path claim makes, so the files under it stay within Windows' 260
TREE = "tree"                    # <root>/phi/tree/<ancestor ids...>/<id>: a node's folder, nested by parent
_TREE = {}                       # by the root store: [the folders it listed with their times], and {id: (rel, node.json)}
RACY_NS = 2_000_000_000          # a folder time this close to a walk is no proof the folder is unchanged since
_MIGRATING = set()               # the roots this process is migrating, so a read inside the migration does not start it
_TMP = re.compile(r"\.tmp-\d+-[0-9a-f]{8}\Z")      # a folder a claim is still making


def _key(home):
    return os.path.normcase(os.path.abspath(home))


def _walk(home):
    """{id: (the node's folder relative to `home`, node.json)} of every node under <home>/phi/tree, and [the folders
    read, so the cache sees a claim]. Depth first: a folder with a node.json is a node, and one that holds only
    folders is a container of the chain; a folder a claim is still making is passed over."""
    held, listed = {}, []
    root = os.path.join(home, "phi", TREE)
    todo = [root] if os.path.isdir(root) else []
    while todo:
        at = todo.pop()
        listed.append(at)
        try:
            names = sorted(n for n in os.listdir(at) if os.path.isdir(os.path.join(at, n)) and not _TMP.search(n))
        except OSError:
            continue
        kids = []
        for n in names:
            sub = os.path.join(at, n)
            d = _read_json(os.path.join(sub, NODE))
            ident = str(d.get("id") or "")
            if ident:
                held.setdefault(ident, (os.path.relpath(sub, home), d))     # an id that stands twice is read at the first
                kids.append(sub)
                continue
            try:
                if all(os.path.isdir(os.path.join(sub, x)) for x in os.listdir(sub)):
                    kids.append(sub)                     # a container: nothing but folders
            except OSError:
                pass
        todo.extend(reversed(kids))
    return held, listed


def _stamp(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def _tree(home):
    """The walk of `home`, kept while the times of <home>/phi, of <home>/.claude and of every folder of the tree it
    listed are unchanged: a claim in any process makes and removes its lock file in <home>/phi and renames its folder
    into one the walk listed, and either changes that folder's time, so a node another process claimed is never
    missed. Where <home>/.claude holds an old nested store the walk is made after migrate_nested moved it in."""
    key = _key(home)
    old = os.path.join(home, ".claude")
    head = (_stamp(os.path.join(home, "phi")), _stamp(old))
    held = _TREE.get(key)
    if held and held[0] == head and all(_stamp(d) == m for d, m in held[1]):
        return held[2]
    if key not in _MIGRATING and os.path.isdir(old) and _old_stores(old):
        migrate_nested(home)
        head = (_stamp(os.path.join(home, "phi")), _stamp(old))
    walked_at = time.time_ns()
    walk = _walk(home)
    stamps = [(d, _stamp(d)) for d in walk[1]]
    # A folder whose time is within RACY_NS of the walk may change again in the same tick of the file system's
    # clock, which on Windows moves in steps of about 16 ms, and the change would leave its time as it was: such a
    # walk is not kept, so the next call walks again, as git treats a racily clean index entry.
    racy = any(m is not None and m >= walked_at - RACY_NS for m in [*head, *(m for _, m in stamps)])
    if not racy:
        _TREE[key] = (head, stamps, walk[0])
    else:
        _TREE.pop(key, None)
    return walk[0]


def forget(home):
    """Drops what nodes() kept for `home`, so the next call walks the folders again."""
    _TREE.pop(_key(home), None)


def nodes(home):
    """{id: the node's folder} of every node of the tree: <home>/phi/tree/<ancestor ids...>/<id>."""
    if not home:
        return {}
    return {k: os.path.join(home, rel) for k, (rel, _) in _tree(home).items()}


def node_record(home, ident):
    """The node.json of `ident`'s node, {} where it has none."""
    held = _tree(home).get(str(ident or "")) if home else None
    return dict(held[1]) if held else {}


def node_time(home, ident):
    """When `ident`'s node was claimed: the time of its node.json, 0.0 where it has none."""
    folder = nodes(home).get(str(ident or "")) if home else ""
    try:
        return os.path.getmtime(os.path.join(folder, NODE)) if folder else 0.0
    except OSError:
        return 0.0


def tree_of(home, ident, parent):
    """The folder a new node `ident` takes: <home>/phi/tree, then the ids of `parent` and each of its ancestors that
    is a node, outermost first, then `ident`."""
    chain, at, seen = [], str(parent or ""), set()
    while at and at not in seen and nodes(home).get(at):
        seen.add(at)
        chain.append(_safe(at))
        at = str(node_record(home, at).get("parent") or "")
    return os.path.join(home, "phi", TREE, *reversed(chain), _safe(ident))


def _empty_up(home, folder):
    """Removes `folder` and each folder above it under <home>/phi/tree that is left empty."""
    stop = os.path.abspath(os.path.join(home, "phi", TREE))
    while folder and os.path.abspath(folder) != stop:
        try:
            os.rmdir(folder)
        except OSError:
            break
        folder = os.path.dirname(folder)


def unclaim(home, ident):
    """Removes the node of `ident` where its folder holds nothing but node.json, as one claim() made in a call that
    then failed, so its name is not stranded, and each container that leaves empty. True where it was removed."""
    folder = nodes(home).get(str(ident or "")) if home else ""
    if not folder or os.listdir(folder) != [NODE]:
        return False
    os.remove(os.path.join(folder, NODE))
    _empty_up(home, folder)
    forget(home)
    return True


def claim(home, ident, kind, parent, sections=(), session="", checkout=""):
    """The folder of the node `ident`, made once: kind is "session", "reader" or "worker", and `parent` the id of the
    session that started it. Under a lock on <home>/phi/nodes.lock, the folder nodes() holds for the id; else the
    folder tree_of gives, made whole under a temporary name with its node.json in it and renamed into place, so no
    folder stands without its node.json and a failed write leaves nothing: the temporary folder is removed and the
    error goes out. node.json holds `place`, one more than the number of nodes whose node.json names the same
    `parent`. A lock given up after three seconds is gone on without, so two claims for one id can make two
    folders: each then reads nodes() again and returns the one it names. "" where the folder's path would pass
    NODE_PATH_MAX, and nothing is made. `session` and `checkout` are kept in node.json where given."""
    ident, parent = str(ident or ""), str(parent or "")
    if not home or not ident:
        return ""
    migrate_nested(home)                          # takes the same lock: before it, never inside
    d = {"id": ident, "kind": kind, "parent": parent, "sections": list(sections),
         "time": time.strftime("%Y-%m-%d %H:%M")}
    if session:
        d["session"] = session
    if checkout:
        d["checkout"] = checkout.replace("\\", "/").rstrip("/")
    with locked(os.path.join(home, "phi", "nodes")):
        have = nodes(home).get(ident)
        if have:
            return have
        folder = tree_of(home, ident, parent)
        if len(os.path.abspath(folder)) > NODE_PATH_MAX:
            return ""
        d["place"] = 1 + sum(1 for k in nodes(home) if str(node_record(home, k).get("parent") or "") == parent)
        os.makedirs(os.path.dirname(folder), exist_ok=True)
        if os.path.isdir(folder):                 # a folder with no node.json: the node.json goes in whole
            _write_raw(os.path.join(folder, NODE), d)
        else:
            tmp = f"{folder}.tmp-{os.getpid()}-{os.urandom(4).hex()}"
            try:
                os.makedirs(tmp)
                _write_raw(os.path.join(tmp, NODE), d)
                os.rename(tmp, folder)
            except OSError:
                there = os.path.isdir(folder)
                _drop(tmp)
                if not there:
                    raise
        forget(home)
        return nodes(home).get(ident) or folder


def _drop(folder):
    """Removes a folder claim() was making, with what is in it."""
    import shutil
    shutil.rmtree(folder, ignore_errors=True)


# --- stores made before p4-phi 0.11.172 ----------------------------------------------------------------------------

def _old_stores(top):
    """[the stores `.../p4` under `top` (<home>/.claude) that hold phi/node.json], by a plain walk that looks for
    p4/phi/node.json at any depth and does not enter a phi folder."""
    out = []
    for at, dirs, _ in os.walk(top):
        dirs[:] = [n for n in dirs if n != "phi"]
        if os.path.basename(at) == "p4" and os.path.isfile(os.path.join(at, "phi", NODE)):
            out.append(at)
    return out


def _old_place(store, top):
    """The place a store held among its siblings, from its path under `top`: `.claude/p4` is 1, `.claude/<i>/.claude/p4`
    is i, and i `.claude` folders then `p4` is i."""
    parts = os.path.relpath(store, top).replace("\\", "/").split("/")
    return int(parts[0]) if parts[0].isdigit() else sum(1 for x in parts if x == ".claude") + 1


def _merge(src, dest):
    """The files and folders of `src` moved into `dest`. A file of the same name that `dest` holds is kept and the
    old one dropped."""
    import shutil
    os.makedirs(dest, exist_ok=True)
    for name in sorted(os.listdir(src)):
        s, t = os.path.join(src, name), os.path.join(dest, name)
        if name.endswith(".lock") and os.path.isfile(s):
            os.remove(s)
        elif not os.path.lexists(t):
            shutil.move(s, t)
        elif os.path.isdir(s) and os.path.isdir(t):
            _merge(s, t)
        elif os.path.isdir(s):
            shutil.rmtree(s, ignore_errors=True)
        else:
            os.remove(s)
    try:
        os.rmdir(src)
    except OSError:
        pass


def _sweep(top):
    """Removes every folder under `top` that holds nothing but emptied folders, `top` too."""
    for at, _dirs, _files in os.walk(top, topdown=False):
        try:
            os.rmdir(at)
        except OSError:
            pass


def migrate_nested(home):
    """Moves each old nested store of `home` into the tree once, for stores made before p4-phi 0.11.172, and is the
    one place that knows the old layout: `.claude/p4` and `.claude/<i>/.claude/p4` under a store, or i `.claude`
    folders and `p4`. Under the nodes lock, it finds every <store>/phi/node.json under <home>/.claude, and, parents
    first, siblings in the order of their node.json `time` and then their old place, moves the store's phi/ into the
    node's tree folder, tree_of(home, id, parent): a session node's phi/sessions/<id>/* and every other file and
    folder of its phi/, directly into the folder, with its node.json given `place` by that order. A file of the same
    name already in the folder is kept and the old one dropped; a session folder of the store that is not the
    node's goes to the flat phi/sessions. Then it removes <home>/.claude wherever it holds nothing but emptied
    folders. A start file's paths are not rewritten: a file a worker still writes at its old path is moved in by a
    later call. Nothing is done where the environment holds P4_PHI_MIGRATE=0, for a store whose sessions still run a
    copy that reads the nested stores. Idempotent: a second run finds nothing. True where a node was moved."""
    top = os.path.join(home, ".claude") if home else ""
    key = _key(home) if home else ""
    if not top or os.environ.get("P4_PHI_MIGRATE") == "0" or key in _MIGRATING or not os.path.isdir(top):
        return False
    moved = False
    _MIGRATING.add(key)
    try:
        with locked(os.path.join(home, "phi", "nodes")):
            found = []
            for store in _old_stores(top):
                d = _read_json(os.path.join(store, "phi", NODE))
                if str(d.get("id") or ""):
                    found.append((str(d.get("time") or ""), _old_place(store, top), store, d))
            found.sort(key=lambda t: (t[0], t[1], t[2]))
            while found:
                ids = {str(t[3]["id"]) for t in found}
                at = next((k for k, t in enumerate(found) if str(t[3].get("parent") or "") not in ids), 0)
                _, _, store, d = found.pop(at)
                ident, parent = str(d["id"]), str(d.get("parent") or "")
                forget(home)
                folder = nodes(home).get(ident)
                if not folder:
                    folder = tree_of(home, ident, parent)
                    d["place"] = 1 + sum(1 for k in nodes(home) if str(node_record(home, k).get("parent") or "") == parent)
                    os.makedirs(folder, exist_ok=True)
                    _write_raw(os.path.join(folder, NODE), d)
                _move_store(home, store, ident, folder)
                moved = True
            _sweep(top)
    finally:
        _MIGRATING.discard(key)
        forget(home)
    return moved


def _move_store(home, store, ident, folder):
    """The phi/ of the old `store` moved into the node's `folder`; its node.json goes."""
    phi = os.path.join(store, "phi")
    own = os.path.join(phi, "sessions", ident)
    if os.path.isdir(own):
        _merge(own, folder)
    sessions = os.path.join(phi, "sessions")
    if os.path.isdir(sessions):
        _merge(sessions, os.path.join(home, "phi", "sessions"))
    try:
        os.remove(os.path.join(phi, NODE))
    except OSError:
        pass
    if os.path.isdir(phi):
        _merge(phi, folder)


def flat(home, sid):
    """The folder a session had before nodes: <home>/phi/sessions/<safe id>, in the root store."""
    return os.path.join(home, "phi", "sessions", _safe(sid))


def session_dirs(home):
    """Every session's folder: the flat ones of <home>/phi/sessions, then each tree node of kind `session`."""
    out = []
    if not home:
        return out
    base = os.path.join(home, "phi", "sessions")
    try:
        out += [os.path.join(base, n) for n in sorted(os.listdir(base))]
    except OSError:
        pass
    folders = nodes(home)
    return out + [folders[k] for k in sorted(folders) if node_record(home, k).get("kind") == "session"]


def session_parents(home):
    """The folders whose list of names shows a new session: the flat phi/sessions, the tree's root, and the folder
    each tree node's folder sits in, where they are there."""
    out = [os.path.join(home, "phi", "sessions"), os.path.join(home, "phi", TREE)]
    out += [os.path.dirname(d) for d in session_dirs(home) if os.path.dirname(d) not in out]
    return [d for d in dict.fromkeys(out) if os.path.isdir(d)]


def _dir(home, sid):
    """A session's folder: its node's folder in the tree where its id has a node, else the flat one."""
    safe = _safe(sid)
    folder = nodes(home).get(safe) if safe else ""
    return folder or flat(home, sid)


def _session(home, sid):
    return _read_json(os.path.join(_dir(home, sid), "session.json")) if sid else {}


def _parent(s):
    sp = s.get("spawnedFrom") if isinstance(s, dict) else None
    return str(sp.get("sessionId") or "") if isinstance(sp, dict) else ""


_SESSION_FILES = {}              # by a session.json's path: its mtime_ns, size and what it held, kept for one process


def _sessions(home):
    """Every session in the store, as its session.json by its sessionId. One message's hook can ask for this eleven
    times over 75 files, so a file is read again only when its time or size changed; each caller gets its own copy
    of a session's top level. The sessions of the tree are read, the flat ones of the root and those
    of each node's folder; an id whose node holds a folder is read there."""
    out = {}
    if not home:
        return out
    held_at = nodes(home)
    for folder in session_dirs(home):
        path = os.path.join(folder, "session.json")
        try:
            st = os.stat(path)
        except OSError:
            _SESSION_FILES.pop(path, None)
            continue
        held = _SESSION_FILES.get(path)
        if not held or held[0] != st.st_mtime_ns or held[1] != st.st_size:
            held = _SESSION_FILES[path] = (st.st_mtime_ns, st.st_size, _read_json(path))
        d = held[2]
        sid = d.get("sessionId")
        if sid and (sid not in out or held_at.get(os.path.basename(folder)) == folder):
            out[sid] = dict(d)
    return out


def _title(s):
    """A session's whole title, as the app lists it, so ezexe finds it in the sidebar by it; its id where it has none."""
    return " ".join(str(s.get("title") or s.get("sessionId") or "").split())


RECORD = None                    # phi.app_record, set by phi.py at import; read lazily otherwise
ROOTED = None                    # phi.record_in, the record looked up in the app folder it was first found in


def archived_in_app(s):
    """True when the app's record of a session has `isArchived`, or the record has gone from the app folder it was
    first found in on this machine. A session no app runs, or one whose app folder this machine lacks, as in a store
    synced from another machine, is never taken as archived by a missing record."""
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
    """True when a session is not live: stale, counted as archived once its work was done, or archived in the app. An
    archive seen in the app is kept in its session.json, so the other machines a store syncs to see it too."""
    if not isinstance(s, dict) or not s.get("sessionId"):
        return True
    if s.get("stale") or s.get("doneRetired") or s.get("archived"):
        return True
    if archived_in_app(s):
        path = os.path.join(_dir(home, s["sessionId"]), "session.json")
        disk = _read_json(path)
        if disk and not disk.get("archived"):
            disk["archived"] = time.strftime("%Y-%m-%d %H:%M")
            _write_json(path, disk)
        s["archived"] = True
        return True
    return False


# --- paths -----------------------------------------------------------------------------------------------------------

# A letter names a drive only on a machine that has drive letters. os.path.splitdrive, by
# https://docs.python.org/3/library/os.path.html: "On systems which do not use drive specifications, drive will always
# be the empty string." Git Bash, which writes E:/x as /e/x, runs on Windows alone, so on macOS and Linux /w/lib is the
# folder lib in /w.
DRIVES = bool(os.path.splitdrive("C:/x")[0])


# tools-reference.md has `PushNotification` send "a desktop notification from a local session", and desktop.md, "Get
# notified when a session finishes", has the app itself notify only "when a Code session finishes a task and you
# aren't currently viewing that session", which does not say that something waits. The tool's own text: "Notify when
# there's a real chance they've walked away and there's something worth coming back for", "Keep the message under 200
# characters, one line, no markdown", and it skips one that would be a duplicate. Not every session lists the tool.
PUSH = ("Where this session's tool list holds `PushNotification`, also send one that says what waits, in one line "
        "under 200 characters: the app's own notice at a turn's end says that a session finished a task, and not "
        "that a card or a question is open.")


def norm(p, base=""):
    """A path or glob as one form: absolute when a base is given, forward slashes, no trailing slash, case folded
    on Windows."""
    p = str(p or "").strip().strip("'\"")
    if not p:
        return ""
    p = p.replace("\\", "/")
    # /e/x as Git Bash writes E:/x, where the machine has drive letters, and /mnt/e/x as WSL does, before the
    # absolute test: on Windows, Python 3.13 and later take a path with one leading slash as not absolute, and would
    # join /e/x onto the base
    p = re.sub(r"^/mnt/([a-zA-Z])(?=/|$)", lambda m: m.group(1).upper() + ":", p)
    if DRIVES:
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
    """True when two path or glob entries can name the same file."""
    ra, rb = _root(a), _root(b)
    return covers(a, b) or covers(b, a) or covers(ra, rb) or covers(rb, ra)


# A slash command as a message writes it: `/goal`, `/plan`, a plugin's `/p4-phi:readings`, a connector's
# `/mcp__github__list_prs`. commands.md: "Commands control Claude Code from inside a session", and "Type `/` to see
# the commands available to you, or type `/` followed by letters to filter". skills.md has a plugin's as
# `/plugin-name:skill-name`, and mcp.md a connector's prompt as `/mcp__servername__promptname`. Each is one slash and
# one name with no dot and no second slash, which is also how a folder at a filesystem's root is written.
COMMAND_RE = re.compile(r"/[A-Za-z_][\w-]*(?::[\w-]+)*")


def command_word(p, n):
    """True when the words `p` are a slash command and no path: one slash and one name, with nothing on disk at
    `n`, the path those words would be. `/goal` and `/plan` in a message name Claude Code's commands, and joined to
    a base on a machine with drive letters they read as the folders `e:/goal` and `e:/plan`. A folder that is there,
    such as `/tmp` or Git Bash's `/e`, stays a path."""
    return bool(COMMAND_RE.fullmatch(p)) and not (drive_ok(n) and os.path.lexists(n))


# A git ref or a repository as a message writes it: `origin/main`, `upstream/release/2`, `refs/heads/main`, `ezexe/p4`.
# gitrevisions, "<refname>": "e.g. master, heads/master, refs/heads/master", and a remote-tracking branch is its
# remote's name and the branch. GitHub names a repository `owner/name`. Each is written as a relative path is, and
# so is a folder still to be made, such as `docs/guides`. So the two are told apart by what the repository at the
# base knows, never by the word's shape: its remotes' names, the owner and name in their addresses, and its branches.
_CONFIGS = {}                    # a base folder -> its repository's git folder, its config's time and what that names
REMOTE = re.compile(r'^\s*\[remote "([^"]+)"\]((?:\n(?!\s*\[).*)*)', re.M)
URL = re.compile(r"^\s*url\s*=\s*(\S+)", re.M)


def _known(base):
    """What the config of the repository at `base` names, as (its git folder, the names of its remotes, the
    `owner/name` of each remote's address in lower case), read with no process started and read again when the file
    changed. A worktree's `.git` is a file that names its git folder, whose `commondir` names the folder the config
    and the branches are in. ('', (), ()) for a folder in no repository."""
    if not base:
        return "", (), ()
    key = norm(base)
    held = _CONFIGS.get(key)
    try:
        if held is None:
            top = repo_of(base)
            git = os.path.join(top, ".git") if top else ""
            if git and os.path.isfile(git):
                with open(git, encoding="utf-8", errors="replace") as f:
                    d = f.read().split("gitdir:", 1)[1].strip()
                git = d if os.path.isabs(d) else os.path.join(top, d)
                common = os.path.join(git, "commondir")
                if os.path.isfile(common):
                    with open(common, encoding="utf-8", errors="replace") as f:
                        c = f.read().strip()
                    git = c if os.path.isabs(c) else os.path.join(git, c)
            held = _CONFIGS[key] = [git, None, (), ()]
        at = os.path.getmtime(os.path.join(held[0], "config")) if held[0] else None
        if at != held[1]:
            with open(os.path.join(held[0], "config"), encoding="utf-8", errors="replace") as f:
                found = REMOTE.findall(f.read())
            slugs = []
            for _, body in found:                  # https://host/owner/name.git, git@host:owner/name.git
                for url in URL.findall(body):
                    tail = re.split(r"[/:]", re.sub(r"\.git$", "", url.rstrip("/"), flags=re.I))[-2:]
                    if len(tail) == 2 and all(tail):
                        slugs.append("/".join(tail).lower())
            held[1], held[2], held[3] = at, tuple(n for n, _ in found), tuple(slugs)
    except (OSError, IndexError, ValueError):
        return "", (), ()
    return held[0], held[2], held[3]


def remotes(base):
    """The names of the remotes of the repository at `base`."""
    return _known(base)[1]


def branch(base, word):
    """True when `word` is a branch of the repository at `base`: a file under its `refs/heads`, or a line of its
    `packed-refs`, where git keeps the refs it packed."""
    git = _known(base)[0]
    if not git or ".." in word:
        return False
    if os.path.isfile(os.path.join(git, "refs", "heads", *word.split("/"))):
        return True
    try:
        with open(os.path.join(git, "packed-refs"), encoding="utf-8", errors="replace") as f:
            return any(line.rstrip().endswith(" refs/heads/" + word) for line in f)
    except OSError:
        return False


def ref_word(p, n, base=""):
    """True when the words `p` name a git ref or a repository and no path, with nothing on disk at `n`, the path
    those words would be, by what the repository at `base` knows: the words are behind the name of one of its
    remotes, as `origin/main` is, they are the owner and name in a remote's address, as `ezexe/p4` is, they are one
    of its branches, or they are behind `refs`, which is git's own folder of refs. A draft named `origin/main` and
    `ezexe/p4` as its area, joined to the project's folder. A word the repository knows nothing of is a path, so a
    folder still to be made, such as `docs/guides`, is one, and so is a folder or file that is there."""
    w = str(p or "").replace(chr(92), "/")
    if "/" not in w or w.startswith(("/", ".", "~")) or re.match(r"^[A-Za-z]:", w) or any(c in w for c in "*?["):
        return False
    parts = w.split("/")
    if not all(parts):
        return False
    _, names, slugs = _known(base)
    known = (parts[0] == "refs" or parts[0] in names or re.sub(r"\.git$", "", w, flags=re.I).lower() in slugs
             or branch(base, w) or (len(parts) == 2 and owner_known(parts[0], base)))
    return known and not (drive_ok(n) and os.path.lexists(n))


def owner_known(word, base):
    """True when `word` is the owner in the address of a remote of the repository at `base`, as `ezexe` is where a
    remote is ezexe/p4, and the project has no folder of that name, so `ezexe/phi` there is that owner's other
    repository and no folder still to be made."""
    owners = {x.split("/")[0] for x in _known(base)[2]}
    return word.lower() in owners and not os.path.lexists(os.path.join(base, word))


# A repository the project's repository knows nothing of, as a message says it is one. Nothing on this machine knows
# `anthropics/claude-code`, and by its shape it is a folder still to be made, so only the message's own words tell
# it. GitHub's "Autolinked references and URLs" writes an issue of another repository `Username/Repository#26` and a
# commit `User/Repository@SHA`, the gh manual gives `-R, --repo [HOST/]OWNER/REPO`, and prose puts the word
# repository or repo directly before the name or directly behind it. A word such as "in" or "of" before it says
# nothing, since a path follows those words as often.
_SLUG = r"[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*?"
_SLUG_END = r"""(?=(?:\.git)?(?:[`'"’#@\s,;:)]|\.?\s|\.?$))"""
_MORE = r"(?:`?(?:\.git)?`?(?:\s*,\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+)`?" + _SLUG + _SLUG_END + r")*"
REPO_SAID = re.compile(
    r"(?:\b(?:repository|repositories|repos|repo)[\s:]+`?|(?<![\w-])(?:-R|--repo)[\s=]+`?|\bgithub\.com[:/]+)"
    r"(" + _SLUG + _SLUG_END + _MORE + r")"
    r"|(?<![\w./\\-])(" + _SLUG + r")(?:\.git)?(?:#\d+\b|@[0-9a-f]{7,40}\b|`?\s+(?:repository|repo)\b)", re.I)
_SLUG_RE = re.compile(r"(?<![\w./\\-])" + _SLUG + _SLUG_END)


def repos_said(text, base=""):
    """The `owner/name` words a text says are repositories, in lower case, REPO_SAID. Each has nothing on disk under
    `base` by that name and an owner that is no folder there, so `the repo lib/sub` and a folder to be made under
    `docs` stay paths."""
    out = []
    for m in REPO_SAID.finditer(str(text or "")):
        for w in ([m.group(2)] if m.group(2) else _SLUG_RE.findall(m.group(1))):
            n = norm(w, base)
            there = drive_ok(n) and (os.path.lexists(n) or os.path.lexists(os.path.dirname(n)))
            if not there and w.lower() not in out:
                out.append(w.lower())
    return out


def _repo_form(p):
    """The words `p` as a repository's name is compared: without a host before it, without `.git`, and without the
    `#26` or `@SHA` of a reference that backticks kept on it, in lower case."""
    w = re.sub(r"^github\.com[:/]+", "", str(p or "").replace(chr(92), "/"), flags=re.I)
    return re.sub(r"(?:\.git)?(?:#\d+|@[0-9a-f]{7,40})?$", "", w, flags=re.I).lower()


def paths_in(text, base=""):
    """The paths a note names: in backticks, or written with a slash. A slash command is no path, command_word, and
    neither is a git ref or a repository's name that the repository at `base` knows, ref_word, nor a repository the
    note itself says is one, repos_said."""
    out = []
    text = re.sub(r"[A-Za-z][\w+.-]*://\S+", " ", str(text or ""))       # a URL is not a path
    said = repos_said(text, base)
    for m in PATH_RE.finditer(text):
        p = m.group(1) or m.group(2)
        if p and ("/" in p or "\\" in p or "." in p) and not p.startswith(("http:", "https:")):
            p = p.rstrip(".,;:)")
            if said and _repo_form(p) in said:
                continue
            n = norm(p, base)
            if n and n not in out and drive_ok(n) and not command_word(p, n) and not ref_word(p, n, base):
                out.append(n)
    return out


# --- owned paths -----------------------------------------------------------------------------------------------------

def shard_of(s):
    return [x for x in (s.get("shard") or []) if isinstance(x, str) and x]


def paths_of(s):
    """A session's paths, in one place: its `shard`, else the strings of its `fileSet`, else []."""
    if not isinstance(s, dict):
        return []
    got = shard_of(s)
    if got:
        return got
    files = s.get("fileSet")
    return [x for x in files if isinstance(x, str) and x] if isinstance(files, list) else []


def above(home, sid):
    """The ids of the sessions above `sid`, nearest first, by _parent, ending at a top or at a parent with no record;
    a loop is cut at an id seen twice."""
    out, seen, cur = [], {sid}, sid
    while True:
        up = _parent(_session(home, cur))
        if not up or up in seen:
            return out
        out.append(up)
        seen.add(up)
        cur = up
        if not _session(home, cur):
            return out


def holders(home, sid, paths, base):
    """[(other id, its title, its path, the path of `paths` it overlaps)] for every running session but `sid` that is
    in neither above(home, sid) nor has `sid` in its own above(), and has a path that overlaps one of `paths`."""
    mine = [n for n in (norm(p, base) for p in paths) if n]
    ups = set(above(home, sid)) if sid else set()
    out = []
    for oid, o in _sessions(home).items():
        if oid == sid or oid in ups or gone(home, o):
            continue
        if sid and sid in above(home, oid):
            continue
        for theirs in paths_of(o):
            n = norm(theirs, o.get("cwd") or base)
            hit = next((m for m in mine if n and overlap(n, m)), None)
            if hit:
                title = o.get("title") or " ".join(str(o.get("task") or "").split())[:60] or str(oid)[:14]
                out.append((oid, title, n, hit))
                break
    return out


def running_children(home, sid):
    """The sessions whose _parent is `sid`, that are not gone and whose paths_of is not empty, as (id, session)."""
    return [(k, v) for k, v in _sessions(home).items() if k != sid and _parent(v) == sid and not gone(home, v)
            and paths_of(v)]


PATHS_ON = "phi/.paths/on"


def mark_paths(home, store):
    """Makes the empty file <store>/phi/.paths/on where a session of the store is not gone and has paths_of, and
    removes it where none has: the hooks module sends an edit to python only where the file is. A marker left behind
    costs one python start for each edit and refuses nothing."""
    path = os.path.join(store or home, *PATHS_ON.split("/"))
    live = any(paths_of(v) and not gone(home, v) for v in _sessions(home).values())
    try:
        if live:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if not os.path.exists(path):
                open(path, "w").close()
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def set_shard(home, sid, paths, base):
    """Keeps `paths` as the session's owned paths, which the address book lists and routes a message by, and makes
    its parent's anchor again. A path a running session holds that is not above this one is refused, and where a
    session above has paths, a path outside the nearest such session's is refused: it is asked of that session."""
    path = os.path.join(_dir(home, sid), "session.json")
    s = _read_json(path)
    if not s:
        raise ValueError("no such session in this store")
    shard = [n for n in (norm(p, base) for p in paths) if n]
    if not shard:
        raise ValueError("name the paths or globs this session alone may change")
    for oid, title, theirs, _ in holders(home, sid, shard, base):
        raise ValueError(f"{theirs} is held by {title} {oid}, which is still running")
    for up in above(home, sid):
        held = paths_of(_session(home, up))
        if held:
            for p in shard:
                if not any(overlap(p, h) for h in held):
                    raise ValueError(f"{p} is outside what {_session(home, up).get('title') or up} {up} holds: "
                                     f"ask it for the path")
            break
    s["shard"] = shard
    _write_json(path, s)
    make_anchor(home, _parent(s), time.strftime("%Y-%m-%d %H:%M"))


def _siblings(home, s):
    """The live sessions beside this one: the same parent's, or for an orchestrator every other orchestrator
    of the store, those detached to top level included, so orchestrators are handed each other's changes as
    siblings. A session that is not live is left out."""
    p = _parent(s)
    return {k: v for k, v in _sessions(home).items() if k != s.get("sessionId") and _parent(v) == p
            and not gone(home, v)}


def warn(home, sid, key, text):
    """A warning kept for a session's next message, once per key, under the session's lock for the whole
    read-modify-write, so two siblings that end their turns at once each warn the same session and both warnings
    are kept. One that cannot get the lock is never dropped and never written
    unlocked: it is kept on a file of its own, which drain_warnings takes in at the next locked write or read."""
    path = os.path.join(_dir(home, sid), "session.json")
    if not os.path.exists(path):                  # no record: nothing to warn, and no folder is made for the lock
        return False
    with locked(path) as lk:
        if not lk.held:
            return _warn_later(home, sid, key, text)
        s = _read_json(path)
        if not s:                                 # the record is there but reads empty, as while another writer's
            return _warn_later(home, sid, key, text)   # os.replace is under way on Windows: kept, never dropped
        took = drain_warnings(home, sid, s)
        added = _warn(s, key, text)
        if took or added:
            _write_json(path, s)
        return added


def _warn_later(home, sid, key, text):
    """A warning that cannot be put on the record now, kept on a file of its own for drain_warnings."""
    name = hashlib.sha1(f"{key} {text}".encode("utf-8", "replace")).hexdigest()[:16]
    _write_json(os.path.join(_dir(home, sid), f"warn-pending-{name}.json"),
                {"key": key, "text": text, "time": time.time()})
    return True


def drain_warnings(home, sid, s):
    """The warnings a locked write could not put on the session, from their own files, oldest first, into `s`; the
    files are removed. Called with the session's lock held. True when `s` changed."""
    rows = []
    for p in glob.glob(os.path.join(_dir(home, sid), "warn-pending-*.json")):
        d = _read_json(p)
        if isinstance(d, dict) and d.get("key") and d.get("text"):
            rows.append((float(d.get("time") or 0), str(d["key"]), str(d["text"])))
        try:
            os.remove(p)
        except OSError:
            pass
    changed = False
    for _, key, text in sorted(rows):
        changed = _warn(s, key, text) or changed
    return changed


def _warn(s, key, text):
    told = s.setdefault("relayWarned", [])
    if key in told:
        return False
    pend = s.setdefault("relayPending", [])
    if any(isinstance(w, dict) and w.get("text") == text for w in pend):
        return False                              # the same words already wait for this session
    up = re.match(r"^plan:([^:]+):[^:]+:up$", key)
    same = [w for w in pend if isinstance(w, dict) and up and re.match(rf"^plan:{re.escape(up.group(1))}:[^:]+:up$",
                                                                      str(w.get("key") or ""))]
    if same:                                      # one line for a child's revisions since the last look
        n = sum(int(w.get("count") or 1) for w in same) + 1
        for w in same:
            pend.remove(w)
            told.append(w.get("key"))
        text = re.sub(r"revised its plan:", f"revised its plan {n} times since you last looked; now:", text, count=1)
        pend.append({"key": key, "text": text, "count": n})
    else:
        pend.append({"key": key, "text": text})
    turns = [w for w in pend if isinstance(w, dict) and str(w.get("key", "")).startswith("turn:")]
    for old in turns[:-TURN_WARNINGS]:                  # only the newest turn reports are kept
        pend.remove(old)
        told.append(old.get("key"))
    return True


def take_warnings(home, sid, s):
    """The texts of the warnings kept for a session, taken off `s` and marked told. Called with the session's lock
    held, by the code that hands them out, so a warning written meanwhile is never lost to that write."""
    drain_warnings(home, sid, s)
    told = s.setdefault("relayWarned", [])
    out = []
    for w in s.get("relayPending") or []:
        if isinstance(w, dict):
            out.append(w["text"])
            if w.get("key") not in told:
                told.append(w.get("key"))
    s["relayPending"] = []
    return out


TURN_WARNINGS = 3          # turn reports kept for one session's next message; older ones are dropped as told


# --- a report that asks ezexe what the sender's context decides ----------------------------------------------------
#
# ezexe is asked only about a change to what a plan is meant to do, approval of a new plan, spend beyond the pools and
# an irreversible action outside the repo. A report line that puts anything else to ezexe, such as "tell me if ezexe
# wants X instead", is a call the sender's context covers: the sender's default stands and the puppeteer relays the line
# as a status, not as a question card.
EZEXE_OWN = re.compile(
    r"\bapprov\w*|\bnew plan\b|\bplan(?:'s|s)?\s+(?:intent|goal|purpose|scope|objective)|meant to do"
    r"|\bspen[dt]\w*|\bbudget|\bcredits?\b|\bpools?\b|\bbilling|\bMax plan"
    r"|\birreversib\w*|(?:can't|cannot|can not|not) be undone|\bforce[- ]push|\bdelet\w*|\bdestroy\w*"
    r"|\bpublish\w*|\bdeploy\w*|outside the repo|\bcredential\w*|\bpassword|\bsecret"
    r"|\bapi[ -]?keys?\b|\bforce(?:d|s)?\b"
    r"|\bpush(?:ing)?\s+(?:\w+\s+){0,2}to\s+(?:origin|the remote|upstream|main)\b"
    r"|\b(?:post|release|token|permission|sign[ -]?in|log[ -]?in|pay|purchase|drop|install|restart)(?:s|ed|ing)?\b",
    re.I)   # the last two lines hold the words of plans.AUTHORITY that reach outside the repo; a push or merge
            # inside it is a PR-split call, so "Should I push it as one PR or two?" is flagged
EZEXE_IF = re.compile(
    r"\b(?:tell|let|say|ping|message|notify|warn|shout|speak up|object|reply)\b[^.?!\n]{0,40}?"
    r"\b(?:if|whether|unless)\s+(?:ezexe|the user)\s+(?:wants?|prefers?|would\s+(?:like|rather|prefer)|likes?|needs?"
    r"|objects?|minds?|disagrees?)\b", re.I)
EZEXE_SHOULD = re.compile(
    r"\b(?:should|shall|do you want|would you like|want me to)\b[^?\n]{0,80}\b(?:(?:one|1|a single|single|the same|same"
    r"|separate|two|2)\s+(?:PRs?|pull requests?|commits?|branch(?:es)?)|(?:which|what)\s+order|in\s+(?:which|what)\s+order)\b"
    r"|\b(?:which|what)\s+order\b"
    r"|\b(?:should|shall)\s+(?:I|we)\s+(?:fix|handle|land|ship|split|order)\b[^?\n]{0,80}\b(?:or|first|before|after)\b",
    re.I)


def asks_ezexe(line):
    """`line`, stripped, when it puts to ezexe a call the sender's context covers; '' otherwise, and '' for a line
    that touches one of ezexe's four matters."""
    text = str(line or "").strip()
    if not text or EZEXE_OWN.search(text):
        return ""
    return text if EZEXE_IF.search(text) or EZEXE_SHOULD.search(text) else ""


def asks_ezexe_in(report):
    """The lines of a report that asks_ezexe flags, in order."""
    return [t for t in (asks_ezexe(l) for l in str(report or "").splitlines()) if t]


def default_status(title, lines):
    """The status line the puppeteer relays for a flagged report, in place of a question card."""
    said = " ".join(f"\"{_short(l, 200)}\"" for l in lines)
    return (f"\"{title}\" put to ezexe what its own context decides: {said} Its default stands, so relay this as a status, "
            f"not as a question card.")


# --- deltas ----------------------------------------------------------------------------------------------------------

def _git(cwd, *args, timeout=None):
    try:
        return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=timeout or GIT_S)
    except (OSError, subprocess.SubprocessError):
        return None


def drive_ok(p):
    """False for a path on a drive this machine does not have, such as `s:/replaces` from a mark's words read as a
    path, which must never reach a filesystem walk."""
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
    if not d:
        return ""
    # A repository's top folder is the nearest one at or above that holds a `.git` git would take, a folder with a
    # HEAD or a worktree's `gitdir:` file, which lstat finds with no process started: asking git
    # `rev-parse --show-toplevel` once a path costs one message's rebase check some 100 calls and 2 s. Git names
    # that folder with its links resolved, so it is resolved here too. Inside a `.git` folder git is asked.
    top = _dot_git_above(d)
    if top is None:
        r = _git(d, "rev-parse", "--show-toplevel")
        return norm(r.stdout.strip()) if r and r.returncode == 0 and r.stdout.strip() else ""
    return norm(os.path.realpath(top)) if top else ""


ABOVE_S = 5.0                    # how long what was found above a folder is believed: a hook's run, a watcher's tick
_ABOVE = {}                      # a folder -> the nearest folder at or above it that holds a `.git`
_ABOVE_AT = [0.0]                # when _ABOVE was started: a watcher lives for hours, and a `git init` comes later


def _is_git(path):
    """True for a `.git` git itself would take: a folder holding HEAD, or a worktree's or submodule's file that
    names its `gitdir:`. An empty or stray `.git` is passed over, as git passes over it and looks further up."""
    try:
        if os.path.isdir(path):
            return os.path.isfile(os.path.join(path, "HEAD"))
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(64).lstrip().startswith("gitdir:")
    except OSError:
        return False


def _dot_git_above(d):
    """The nearest folder at or above `d` that holds a `.git`, '' when none does, None when `d` lies inside a `.git`
    folder, where git answers differently."""
    d = os.path.abspath(d)
    if re.search(r"[\\/]\.git(?:[\\/]|$)", d):
        return None
    if time.time() - _ABOVE_AT[0] > ABOVE_S:
        _ABOVE.clear()
        _ABOVE_AT[0] = time.time()
    walked, cur, found = [], d, ""
    while True:
        if cur in _ABOVE:
            found = _ABOVE[cur]
            break
        walked.append(cur)
        if os.path.lexists(os.path.join(cur, ".git")) and _is_git(os.path.join(cur, ".git")):
            found = cur
            break
        up = os.path.dirname(cur)
        if up == cur:
            break
        cur = up
    for w in walked:
        _ABOVE[w] = found
    return found


def heads(repos):
    """Each repository as '<repo>@<branch> <sha8>'."""
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
    """<parent>/anchor.json; for the orchestrators, which nobody started, phi/anchor.json."""
    if not parent:
        return os.path.join(home, "phi", "anchor.json")
    return os.path.join(_dir(home, parent), "anchor.json")


def make_anchor(home, parent, now):
    """Makes <parent>/anchor.json again from each child's marked notes, owned paths, task list and parent step and
    from the parent's own marked notes, owned paths and task list; with no parent, phi/anchor.json from the
    orchestrators' marked notes, owned paths and task lists. A child's node carries the time of its latest delta
    and none of that delta's heads or files, which lie in the child's own worktree. A finished child that a newer
    note supersedes is fenced off here. Its version goes up only when that content changed. Returns the anchor."""
    import plans                                  # the task lists: each session's steps, statuses and current step
    root = not parent                             # the orchestrators, which nobody started
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
            nodes[sid] = {"title": _title(s), "time": str((last or {}).get("time") or ""), "marks": marks,
                          "shard": shard_of(s), "plan": plan, "root": str(s.get("rootStep") or "")}
    own = {} if root else {"title": _title(every.get(parent, {})), "marks": _all_marks(home, parent),
                           "shard": shard_of(every.get(parent, {})), "plan": plans.summary(home, parent)}
    if not root:                                  # a finished child a newer note supersedes is fenced off here
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
    # every repository's status is asked at once, not one after another, and of what git lists only the entries
    # whose file name is one asked about are put in one form: putting all of them in one form costs a message 60 ms
    # in a work tree with thousands of untracked files
    runs = []
    for repo, fs in by_repo.items():
        try:
            runs.append((repo, fs, subprocess.Popen(
                ["git", "-C", repo, "status", "--porcelain", "-z", "--untracked-files=all"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True,
                encoding="utf-8", errors="replace")))
        except OSError:
            continue
    for repo, fs, proc in runs:
        try:
            listed, _ = proc.communicate(timeout=GIT_S)
        except (OSError, subprocess.SubprocessError):
            proc.kill()
            continue
        if proc.returncode != 0:
            continue
        names = {f.rsplit("/", 1)[-1] for f in fs}
        dirty = set()
        for item in listed.split("\0"):
            if len(item) > 3 and norm(item[3:].replace("\\", "/").rsplit("/", 1)[-1]) in names:
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
    """A path as a message shows it: relative to the session's project when it lies there."""
    b = norm(base) if base else ""
    if b and (p == b or p.startswith(b + "/")):
        return p[len(b) + 1:] or "."
    return p


FAR_WHOLE = 400                  # notes that do not touch a session are still shown when all of them are this short
STOP_HEAD = "phi (p4-phi): stop before any tool runs. "      # the head of the warnings, which lead a session's text


def stop_line(text):
    """rebase's text as its warnings and the rest: the warnings ask the session to act, so phi.py puts them first."""
    if not text.startswith(STOP_HEAD):
        return "", text
    line, _, rest = text.partition("\n\n")
    return line, rest


def page_of(home, nid):
    return os.path.join(_dir(home, nid), "session.md").replace("\\", "/")


def rebase(home, sid, room, fair_cut, touches=None):
    """Returns the text a session is given at this message, '' when nothing changed, and whether its session.json
    changed. With `touches`, a sibling's deprecation or replacement is given in full only when its words touch this
    session's task or open steps; the rest is a count and the pages that hold them. The warnings other code kept
    with relay.warn are given whole, each once, since a hook's text past the app's cap goes to the app's own file.
    The notes are cut to `room`, the rest named by count and by their sessions' pages, and none of it comes again.
    No path of this session is held against another's notes or owned paths: each session that writes works in a
    git worktree of its own, so the two never name one file on disk."""
    path = os.path.join(_dir(home, sid), "session.json")
    with locked(path) as lk:                      # the warnings are emptied under the lock relay.warn holds
        return _rebase(home, sid, room, fair_cut, touches, path, lk.held)


def _rebase(home, sid, room, fair_cut, touches, path, held):
    s = _read_json(path)
    if not s:
        return "", False
    if s.get("stale"):
        st = s["stale"]
        if st.get("told"):
            return "", False
        st["told"] = True
        s["anchorSeen"] = max(int(s.get("anchorSeen") or 0), int(st.get("anchorVersion") or 0))
        _write_json(path, s)
        ready_page(home)                          # messaged again, it is live: off the page
        return (f"phi (p4-phi): this session's work is superseded and it is stale in the session tree: "
                f"\"{st.get('note')}\". Re-base onto that before going on; its outcome is kept as a note on its "
                f"parent session."), True
    warnings = take_warnings(home, sid, s) if held else []     # not held: they wait for the next message
    parent = _parent(s)
    anchor = _read_json(anchor_path(home, parent))
    if "anchorSeen" not in s:                     # the first look takes what is there as seen and hands none of it
        s["anchorSeen"] = int(anchor.get("version") or 0)
        s["marksGiven"] = mark_keys(home, parent)
    seen = int(s.get("anchorSeen") or 0)
    given = s.setdefault("marksGiven", [])
    version = int(anchor.get("version") or 0)
    fresh = version > seen
    marks = []
    if fresh:
        changed = anchor.get("changedAt") or {}
        nodes = sorted((anchor.get("nodes") or {}).items())
        par = anchor.get("parent") or {}
        for nid, n in nodes + [(parent, par)]:
            if nid == sid or int(changed.get(nid) or 0) <= seen:
                continue
            for m in n.get("marks") or []:
                key = mark_key(nid, m)                 # each mark handed once, however often its session changes
                if key not in given:
                    given.append(key)
                    marks.append((nid, n.get("title") or nid, m))
        s["anchorSeen"] = version
        del given[:-400]                               # the newest keys are enough to tell a mark already given
    if not (warnings or marks):
        _write_json(path, s)
        return "", fresh
    parts, used = [], 0
    if warnings:
        line = STOP_HEAD + " ".join(f"({k + 1}) {w}" for k, w in enumerate(warnings))
        parts.append(line)
        used += len(line) + 2
    if marks:
        near = [x for x in marks if touches is None or touches(str(x[2].get("claim") or ""))]
        far = [x for x in marks if x not in near]
        if far and sum(len(str(m.get("claim"))) + len(str(m.get("source"))) + len(str(tt)) + 60
                       for _, tt, m in far) <= FAR_WHOLE:
            near, far = marks, []                      # shorter in full than the line that would name their pages
        bits = []
        if near:
            lines = [f"- \"{t}\" `{nid}`: {m.get('claim')}; source: {m.get('source')}" for nid, t, m in near]
            left = max(400, room - used - 420 - (330 if far else 0))
            whole = sum(len(x) + 1 for x in lines) <= left
            if not whole:
                keep = max(1, min(len(lines), left // 400))     # as many as get a readable share, the newest
                far = near[:len(near) - keep] + far
                near = near[len(near) - keep:]
                lines = fair_cut(lines[-keep:], left - keep)
            pages = sorted({page_of(home, nid) for nid, _, _ in near})
            bits.append(f"phi (p4-phi): what the sessions beside this one deprecated or replaced since it last "
                        f"looked, at anchor v{version}, "
                        + ("in full" if whole else f"cut to the room beside one prompt and whole on "
                                                   f"{', '.join(pages[:3])}") + ":\n" + "\n".join(lines))
        if far:
            by = {}
            for nid, _, _ in far:
                by[nid] = by.get(nid, 0) + 1
            named = ", ".join(f"{n} on {page_of(home, nid)}" for nid, n in sorted(by.items())[:3])
            more = (f", and the pages of {len(by) - 3} more sessions under "
                    f"{os.path.join(home, 'phi').replace(chr(92), '/')}") \
                if len(by) > 3 else ""
            bits.append(f"phi (p4-phi): deprecation or replacement notes not shown: {len(far)}, from the sessions "
                        f"beside this one at anchor v{version}. They do not touch this session's task or open "
                        f"steps, or did not fit, and are whole on their sessions' pages: {named}{more}.")
        parts += bits
        used += sum(len(x) + 2 for x in bits)
    _write_json(path, s)
    return "\n\n".join(parts), True


def _short(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 4] + " ..."


DANGLING = frozenset("""a an the that which who whose of to for in on at by with from under over into onto and or but as
than its their this these those is are was were be when where while if so not no only every each because since unless
until then""".split())
SUBORDINATE = frozenset("that which who whose when where while because since if unless until so".split())
SENTENCE_END = re.compile(r"[.!?](?=\s)")
CLAUSE_END = re.compile(r"[,;:](?=\s)|\s[-–—]\s")


def clause_cut(text, n):
    """A title's worth of `text` in at most `n` characters, ended at a sentence or a clause and never mid-phrase:
    whole when it fits; else up to the last sentence end in the room, else the last clause mark, else the words
    before the last subordinate clause that the room cuts through, with no dangling word left at the end. Nothing
    marks that it was cut: what is left reads as a title."""
    s = " ".join(str(text or "").split())
    if len(s) <= n:
        return s
    head = s[:n + 1]
    for marks in (SENTENCE_END, CLAUSE_END):
        ends = [m.start() for m in marks.finditer(head) if m.start() >= n // 3]
        if ends:
            return head[:ends[-1]].rstrip(" ,;:.-–—")
    return whole_phrase(head[:n].rsplit(" ", 1)[0] if " " in head[:n] else head[:n])


def whole_phrase(cut):
    """Words that were cut off mid-sentence, ended where a phrase ends: a subordinate clause the cut ran through is
    dropped only when it is left with no more than its opening words, and no dangling word stays at the end."""
    kept = " ".join(str(cut or "").split()).split(" ")
    subs = [k for k, w in enumerate(kept) if w.lower().strip(",;:.") in SUBORDINATE and k >= 2]
    if subs and len(kept) - subs[-1] <= 3:
        kept = kept[:subs[-1]]
    while len(kept) > 1 and kept[-1].lower().strip(",;:.") in DANGLING:
        kept.pop()
    return " ".join(kept).rstrip(" ,;:.-–—")


# --- routing ---------------------------------------------------------------------------------------------------------

def names_nothing(p, home, base=""):
    """True when a path names no one session's owned paths or scope: the project's root, the store, a folder above
    either, or a drive's root. A brief that names the project names everything in it, so the path routes no message
    to a session and counts toward no fork's share."""
    p = norm(p)
    if not p or p == "/" or re.fullmatch(r"[a-z]:/?", p, re.I):
        return True
    h = norm(home) if home else ""
    roots = [x for x in (h, norm(os.path.dirname(os.path.dirname(h))) if h else "", norm(base) if base else "") if x]
    return any(covers(p, r) for r in roots)


def route_text(home, s, text, store=""):
    """The line beside a message that names a path among another live session's owned paths: the message belongs
    to that session, so this one is told to send it there with SendMessage. The owner is found by the address
    book, book.holders, which reads each path from its own repository's root and so finds a worker in a git
    worktree of its own, where one absolute path held against another never meets. The files a brief covers and
    an issue route nothing here: the address book reads those before a message is sent."""
    import book
    got = book.holders(home, s, text, store, owned=True)
    if not got:
        return ""
    e, what = got[0]
    return (f"phi (p4-phi): this message names {what}, among the owned paths of \"{e['title']}\" `{e['id']}`. Send "
            f"it there with SendMessage to {e['id']} instead of working on it here.")


# --- fork or fresh -----------------------------------------------------------------------------------------------------
#
# On this machine's app records, 84 children with a parent transcript on disk: the parent's transcript held a median
# 2.9 MB when a fork started, with quartiles of 1.9 and 4.4 MB, and 2.1 MB when a fresh session did. Above 1 MB a
# parent had a median of 2 to 27 of ezexe's turns behind it, and already held 0.76 to 0.86 of the brief's words: a
# fork there carries the rest of the parent's work into the child, while a brief carries most of what the child
# needs. Under 1 MB, 17 of 22 children were fresh and the parent held little. So a fork is advised only from a parent
# whose transcript is at most FORK_MAX_BYTES, for a child whose paths cover at least FORK_SHARE of the parent's
# scope; otherwise a fresh session.
#
# A start that names another place, by `cwd`, `host`, `preset`, `environment`, `repository` or a `target` other than
# local, is not this session's folder to share: the partition of a start's paths is not read for it.
ELSEWHERE = ("cwd", "host", "preset", "environment", "repository")

FORK_MAX_BYTES = 1024 * 1024
FORK_SHARE = 0.5


def scope_of(home, sid):
    """What a session covers: its owned paths, else the files its latest delta names. Its children's files are no
    part of it: each lies in the child's own worktree, where no path a message or a brief names from here leads."""
    s = _session(home, sid)
    if shard_of(s):
        return shard_of(s)
    files = set()
    for r in reversed(_rows(os.path.join(_dir(home, sid), "turns.jsonl"))):
        if isinstance(r.get("delta"), dict):
            files.update(r["delta"].get("files") or [])
            break
    return sorted(files)


def advise_start(home, parent, tool_input, transcript_bytes):
    """What is advised for a start_session call from `parent`: "fork" or "fresh", and why. By the size of the
    parent's transcript and how much of the parent's scope the brief's paths cover, for a writer's start as for any."""
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
                                                                                    ": the brief names no path"))
    return "fresh", "; ".join(why) + ". A fresh session given a brief and p4-phi's slice of the anchor starts on its " \
                                      "own task alone"


def pin_text(s):
    """The line that keeps a forked child on its own agenda, above the conversation it inherited."""
    task = _short(s.get("task") or "", 300)
    if not task:
        return ""
    shard = shard_of(s)
    return (f"phi (p4-phi): this session is a fork; the conversation above its first message is the parent's, "
            f"inherited as context and not its agenda. Its own task: \"{task}\""
            + (f"; its owned paths: {', '.join(shard[:5])}." if shard else ". It has declared no owned paths yet: "
               f"`phi.py shard <paths>` names what it alone changes."))


def slice_text(home, s):
    """A fresh child's start: what its parent's anchor and notes hold for the child's paths, its owned paths or
    those its task names, and nothing else: the deprecations and replacements that name them and the parent's notes
    about them. It names no file another session changed and no head to build on, since those lie in the other
    sessions' worktrees. One line when the parent has nothing for them."""
    parent = _parent(s)
    if not parent:
        return ""
    anchor = _read_json(anchor_path(home, parent))
    ps = _session(home, parent)
    base = s.get("cwd") or ps.get("cwd") or ""
    mine = shard_of(s) or paths_in(s.get("task") or "", base)
    ver = int(anchor.get("version") or 0)
    if not mine:
        return ""                                 # nothing to cut the anchor by: phi.background_text says the rest
    head = (f"phi (p4-phi): what the parent, \"{_title(ps)}\", has for this session's paths, "
            f"{', '.join(show(p, base) for p in mine[:5])}, from its anchor v{ver}.")   # by its title alone: no
    # session is handed a run of the words of a prompt sent to another
    marks = []
    every = list((anchor.get("nodes") or {}).items()) + [(parent, anchor.get("parent") or {})]
    for nid, n in every:
        if nid == s.get("sessionId"):
            continue
        for m in n.get("marks") or []:
            if any(overlap(p, x) for p in m.get("paths") or [] for x in mine):
                marks.append(f"- \"{n.get('title') or nid}\": {m.get('claim')}; source: {m.get('source')}")
    notes = [f"- {_short(r.get('claim'), 300)}; source: {_short(r.get('source'), 120)}"
             for r in _rows(os.path.join(_dir(home, parent), "notes.jsonl"))
             if not str(r.get("claim") or "").lower().startswith(MARKS)
             and any(overlap(p, x) for p in paths_in(r.get("claim"), base) for x in mine)]
    if not (marks or notes):
        return head + " It has nothing for them yet."
    out = [head]
    if marks:
        out += ["Deprecated or replaced there, in full:"] + marks
    if notes:
        out += ["Notes about them:"] + notes
    return "\n".join(out)


def anchor_version(home, parent):
    return int(_read_json(anchor_path(home, parent)).get("version") or 0) if parent else 0


def mark_keys(home, parent):
    """The keys of every mark the parent's anchor holds: what a child's start already carries."""
    a = _read_json(anchor_path(home, parent)) if parent else {}
    nodes = list((a.get("nodes") or {}).items()) + [(parent, a.get("parent") or {})]
    return [mark_key(nid, m) for nid, n in nodes for m in n.get("marks") or []]


def child_paths(home, s):
    """The paths a child's start is cut to: its owned paths, else those its task names; [] when neither names any."""
    base = s.get("cwd") or _session(home, _parent(s)).get("cwd") or ""
    return shard_of(s) or paths_in(s.get("task") or "", base)


# --- phi/ tracked in the store -------------------------------------------------------------------------------------------
#
# When the store's p4.json sets phi.track, the session tree reaches the other machines through the store's git, like
# the rest of the store: session.json, turns.jsonl, notes.jsonl, reports.jsonl, node.json, plan.json and
# anchor.json are tracked, and what is per machine or made again from them is ignored. While phi.track is off, which is the default, the whole
# tree is ignored, as UNTRACKED lists. The ignore lines are made sure of here, before anything is added, since the
# layout hook that seeds the rest of .gitignore runs beside this one at a start. A node's folder is a plain folder of
# the root store, so each pattern that opens `phi/sessions/*/` has a twin that opens `phi/tree/**/`, where the nodes'
# folders are, and `phi/sessions/` itself, the tree while phi.track is off, one that is `phi/tree/`.

SESSIONS, SESSIONS_TREE = "phi/sessions/*/", "phi/tree/**/"


def _twins(lines):
    """Each line, and after each that opens `phi/sessions/*/` or is `phi/sessions/` its twin for the tree of nodes'
    folders, in the same order."""
    out = []
    for x in lines:
        out.append(x)
        if x.startswith(SESSIONS):
            out.append(SESSIONS_TREE + x[len(SESSIONS):])
        elif x == "phi/sessions/":
            out.append("phi/tree/")
    return tuple(out)


IGNORED = ("phi/sessions/*/log.jsonl", "phi/sessions/*/session.md", "phi/sessions.md", "phi/rules.md",
           "phi/catchup.json", "phi/**/*.tmp", "phi/**/*.lock",
           # the archive a layout move or a migration keeps verbatim is tracked whole, whatever its files are named;
           # these come after the two lines above, which they except it from
           "!phi/archive/**/*.tmp", "!phi/archive/**/*.lock",
           "phi/sessions/*/.calls/", "phi/.agents/", "phi/.nudge/", "phi/.paths/",
           # the watcher's pages are made again from the records; routes.jsonl is kept
           "phi/sessions/*/ledger.md", "phi/sessions/*/ledger.json", "phi/sessions/*/ledger.sig",
           "phi/sessions/*/watcher.json", "phi/meta-ledger.md", "phi/.issue-states.json", "phi/.routes-checked",
           # a session's context fill and plan limits, which the hooks module writes for this machine's session
           "phi/sessions/*/usage.json",
           # what git and GitHub answered once on this machine: the commits found landed and the issues found closed
           "phi/.cache/",
           # the open issues a puppeteer's watcher last listed from GitHub, listed again at its next slow look
           "phi/sessions/*/open-issues.json",
           # the sessions waiting to be archived, made again from the records
           "phi/ready-to-archive.md",
           # what one hook read from the app's records, kept so the next reads one file: this machine's alone
           "phi/.cache/")
IGNORED = _twins(IGNORED)
TRACKED_MARK = "p4-phi-tracked"


FILTER_ATTR = "phi/** filter=p4path"
ARCHIVE_ATTR = "phi/archive/** -filter"      # the archive is kept verbatim: no path in it is rewritten
ATTRS = (FILTER_ATTR, ARCHIVE_ATTR)        # phi/** holds phi/tree


def _path_filter(home, g=None):
    """The store's git runs pathfilter.py on phi/ but its archive: set in this machine's git config, which names
    this machine's python and plugin, and in .gitattributes, which every machine shares, where the archive's line
    follows the filter's, since the last line that matches a path decides it. True when .gitattributes changed.
    `g` runs its git calls, as relay.track's hook budget; a value it could not read is left to a later call."""
    run = g or (lambda *a: _git(home, *a))
    py = sys.executable.replace("\\", "/")
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pathfilter.py").replace("\\", "/")
    for kind in ("clean", "smudge"):
        want = f'"{py}" -I "{script}" {kind}'
        have = run("config", "--local", "--get", f"filter.p4path.{kind}")
        if have is not None and have.stdout.strip() != want:
            run("config", "--local", f"filter.p4path.{kind}", want)
    ga = os.path.join(home, ".gitattributes")
    try:
        with open(ga, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    have = {x.strip() for x in text.splitlines()}
    missing = [x for x in ATTRS if x not in have]
    if not missing:
        return False
    with open(ga, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if not text or text.endswith("\n") else "\n") + "# the project's root as {project} in git, "
                "and the archive verbatim, by p4-phi\n" + "".join(x + "\n" for x in missing))
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
                    "files, by p4-phi\n" + "".join(x + "\n" for x in missing))
    return bool(missing)


# While phi.track is off nothing of the session tree is ever committed, so all of it is ignored, under its own
# marker line; when tracking is turned on the block comes out again, and the per-machine lines of IGNORED stay.
UNTRACKED_MARK = "# the session tree, while phi.track is off (p4-phi)"
UNTRACKED = _twins(("phi/sessions/", "phi/anchor.json", "phi/reports.jsonl", "phi/start-requests.jsonl"))


def tree_ignore(home, tracked):
    """The store's .gitignore with the untracked tree's block present while tracking is off, or taken out while it
    is on. True when the file changed."""
    gi = os.path.join(home, ".gitignore")
    try:
        with open(gi, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    lines = text.splitlines()
    if UNTRACKED_MARK in lines:
        k = lines.index(UNTRACKED_MARK)
        end = k + 1
        while end < len(lines) and lines[end].strip() in UNTRACKED:
            end += 1
        if not tracked and set(lines[k + 1:end]) >= set(UNTRACKED):
            return False
        lines = lines[:k] + lines[end:]
    elif tracked:
        return False
    if not tracked:
        lines += [UNTRACKED_MARK, *UNTRACKED]
    if not os.path.isdir(home):
        return False
    with open(gi, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))
    return True


def track(home, first_only=False, wait=False):
    """Stages phi/ in the store's git, and the first time commits it on its own. Only when the store's p4.json sets
    phi.track; otherwise the session tree is kept ignored. The IGNORED lines are made sure of either way, so the
    watcher's state files never show as untracked. The project's root goes into git as {project} through the store's
    path filter, so another machine's checkout names its own files.
    Inside a hook its git calls end within TRACK_HOOK_S. The first commit, which can take far longer, is run by
    track_first in a process of its own that the hook starts and does not wait on; `wait` runs it here instead.
    Returns True when the first commit was made in this call."""
    try:
        import p4conf
        on = bool((p4conf.section(home, "phi", write=False) or {}).get("track"))
    except Exception:  # noqa: BLE001
        return False
    try:
        dropped = tree_ignore(home, on)
    except OSError:
        dropped = False
    if not on:
        try:                # the made-again files at the root of phi/ are ignored while tracking is off too
            if os.path.isdir(home):
                _ignore_lines(home)
        except OSError:
            pass
        return False
    deadline = time.time() + TRACK_HOOK_S

    def g(*args):
        left = deadline - time.time()
        return _git(home, *args, timeout=min(GIT_S, left)) if left > 0 else None
    top = g("rev-parse", "--show-toplevel")
    if not top or top.returncode != 0 or norm(top.stdout.strip()) != norm(home):
        return False
    gd = g("rev-parse", "--absolute-git-dir")
    if not gd or gd.returncode != 0:
        return False
    gd = gd.stdout.strip()
    first = not os.path.exists(os.path.join(gd, TRACKED_MARK))
    if first_only and not first:
        return False
    changed = _ignore_lines(home) or dropped
    attrs = _path_filter(home, g)
    if not first:
        if deadline - time.time() >= TRACK_ADD_LEFT_S:   # a git stopped mid-add would leave its index.lock behind
            g("add", "-A", "--", *_tracked(home), *([".gitignore"] if changed else []),
              *([".gitattributes"] if attrs else []))
        return False
    _owe(gd, [".gitignore"] if changed else [], [".gitattributes"] if attrs else [])
    if wait:
        return track_first(home)
    state = _read_json(os.path.join(gd, TRACK_STATE))
    if time.time() >= float(state.get("next") or 0) and not _track_running(gd):
        _start_track_first(home)
    return False


def _tracked(home):
    """What the store's git takes of the session tree: the root's phi/, which holds phi/tree."""
    forget(home)
    return ["phi"]


TRACK_ADD_LEFT_S = 2.0           # the least of the hook's budget a staging add starts with
TRACK_STALE = 5                  # a track-first lock untouched for this many TRACK_S is a run that died
TRACK_STATE = "p4-phi-track.json"  # in the store's git directory: what the first commit owes, and its failures
TRACK_LOCK = "p4-phi-track.lock"
TRACK_SUBJECT = "phi: the session tree, tracked"


def _owe(gd, *paths):
    """Records in the git directory the paths the tree's first commit owes beside phi/, kept until it is made, so a
    retry commits the .gitignore and .gitattributes an earlier call changed."""
    path = os.path.join(gd, TRACK_STATE)
    st = _read_json(path)
    owed = list(st.get("owed") or [])
    more = [x for ps in paths for x in ps if x not in owed]
    if more or not os.path.exists(path):
        st["owed"] = owed + more
        _write_json(path, st)


def _track_running(gd):
    try:
        return time.time() - os.path.getmtime(os.path.join(gd, TRACK_LOCK)) < TRACK_STALE * TRACK_S
    except OSError:
        return False


def _start_track_first(home):
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen([sys.executable, "-I", "-X", "utf8", os.path.abspath(__file__), "track-first", home],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, start_new_session=os.name != "nt", close_fds=True)
    except OSError:
        pass                               # unmarked: the next hook starts it again


def track_first(home):
    """The tree's first commit, of phi/ and what earlier calls recorded it owes, with TRACK_S for each git call.
    One runs at a time, under a lock in the git directory. A commit already made, as by a run that ended before its
    mark, is found and not made again. A failure is kept with its reason and tried again only after a wait that
    doubles each time, up to an hour; track_notice words it once. True when the tree is now marked tracked."""
    gd = _git(home, "rev-parse", "--absolute-git-dir", timeout=TRACK_S)
    if not gd or gd.returncode != 0:
        return False
    gd = gd.stdout.strip()
    mark, spath, lock = (os.path.join(gd, n) for n in (TRACKED_MARK, TRACK_STATE, TRACK_LOCK))
    if os.path.exists(mark):
        return False
    try:
        if os.path.exists(lock) and not _track_running(gd):
            dead = f"{lock}.dead-{os.getpid()}"
            os.replace(lock, dead)         # a run that died long ago; of two runs that find it, one moves it
            if time.time() - os.path.getmtime(dead) < TRACK_STALE * TRACK_S:
                os.replace(dead, lock)     # a live run's lock, made after the check: put back and left to it
                return False
            os.remove(dead)
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except OSError:
        return False                       # another run holds it

    def git(*args):
        try:
            os.utime(lock)                 # a live run's lock is never taken for a dead one's
        except OSError:
            pass
        return _git(home, *args, timeout=TRACK_S)
    try:
        st = _read_json(spath)
        if time.time() < float(st.get("next") or 0):
            return False
        landed = git("log", "-1", "--format=%H", "--fixed-strings", f"--grep={TRACK_SUBJECT}")
        if not (landed and landed.returncode == 0 and landed.stdout.strip()):
            paths = _tracked(home) + [x for x in st.get("owed") or [] if os.path.exists(os.path.join(home, x))]
            if _path_filter(home, git) and ".gitattributes" not in paths:
                paths.append(".gitattributes")
            why, r = "", None
            have = git("config", "--local", "--get", "filter.p4path.clean")
            if have is None or have.returncode != 0:   # without it git takes this machine's paths into history
                why = "the path filter is not set"
            steps = () if why else (("add", "-A", "--", *paths), ("diff", "--cached", "--name-only", "--", *paths))
            for args in steps:
                r = git(*args)
                if r is None or r.returncode != 0:
                    why = (r.stderr.strip() if r is not None else "") or f"git {args[0]} did not finish"
                    break
            if not why and r.stdout.strip():
                r = git("-c", "user.name=p4", "-c", "user.email=p4@localhost", "commit", "-q",
                        "--no-verify", "-m", TRACK_SUBJECT, "--", *paths)
                if r is None or r.returncode != 0:
                    why = (r.stderr.strip() if r is not None else "") or "git commit did not finish"
            if why:
                st = dict(_read_json(spath))      # what hooks owed meanwhile is kept
                n = int(st.get("fails") or 0) + 1
                st.update(fails=n, next=time.time() + min(3600, 60 * 2 ** (n - 1)),
                          reason=why.strip().splitlines()[0][:300],
                          told=bool(st.get("told")))
                _write_json(spath, st)
                return False
        with open(mark, "w", encoding="utf-8") as f:
            f.write("tracked\n")
        owed = [x for x in _read_json(spath).get("owed") or [] if os.path.exists(os.path.join(home, x))]
        if owed:                           # what a hook recorded meanwhile, or a commit found made did not hold
            git("add", "--", *owed)
        try:
            os.remove(spath)
        except OSError:
            pass
        return True
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def track_notice(home):
    """One line, once, when the tree's first commit has failed: the reason, and when it is tried again; else ''."""
    gd = _git(home, "rev-parse", "--absolute-git-dir")
    if not gd or gd.returncode != 0:
        return ""
    spath = os.path.join(gd.stdout.strip(), TRACK_STATE)
    st = _read_json(spath)
    if not st.get("fails") or st.get("told"):
        return ""
    st["told"] = True
    _write_json(spath, st)
    when = time.strftime("%H:%M", time.localtime(float(st.get("next") or 0)))
    n = int(st["fails"])
    return (f"phi (p4-phi): the session tree's first commit in {home} failed, {n} time{'s' if n != 1 else ''}: "
            f"{st.get('reason')}. It is tried again from {when}, outside the hooks.")


# --- one session tree for several stores: phi.home --------------------------------------------------------------------
#
# Related repositories can share one session tree: a project's p4.json names `phi.home`, the git remote of the store
# that holds the tree, which holds on every machine where a path would not. Each machine resolves remotes to its own
# store folders through a map kept per user, beside Claude Code's settings and in no repository: p4-stores.json,
# written at a session's start for a store whose p4.json names a home, when the folder kept for that remote differs.
# The project's session tree goes to the phi/ of the store `phi.home` names; its memory and rules stay
# its own.

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
    home; the store that is the home names itself there. No file outside a repository is written for anyone who
    never set one. Quiet on any failure."""
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
    """Where the session tree of `store`'s project lives, and the remote p4.json names when this machine has not
    found it, else ''."""
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


# --- stale sessions ---------------------------------------------------------------------------------------------------
#
# A finished child whose work a newer note supersedes holds a picture of the tree that is out of date. Anything handed
# to it or from it can only push the others back to that picture, round and round. So it is fenced off at once: its
# still-true outcome is kept as one note on its parent, it is left out of the anchor, the slices and what relay.py
# hands the other sessions, and its parent is told it is counted as archived. A stale child that is messaged again is
# handed what superseded it, and is live again only when its next turn ends having seen that anchor.

def finished(home, sid):
    """True when a session's work is over: its last turn was shown done or its task list has steps and none still
    open, and nothing it changed is left uncommitted. A session with no task list and no done turn is never taken as
    finished."""
    import plans
    turns = _rows(os.path.join(_dir(home, sid), "turns.jsonl"))
    if not turns:
        return False
    steps = plans.load(home, sid).get("steps") or []
    over = bool(turns[-1].get("done")) or (bool(steps) and all(x.get("status") == "completed" for x in steps))
    return over and not uncommitted(edited_files(home, sid))


def superseded(home, sid, s, others_marks):
    """The newer note that supersedes a finished session's work: one whose words bear on its parent step. None when
    there is none, and for a session with no parent step. No path a note names is held against the session's files
    or owned paths: those lie in the session's own worktree, on its own branch, which no other session's note
    replaces on disk, and whether its work stands beside another's is settled when the tree's orchestrator merges
    the branches."""
    import plans
    turns = _rows(os.path.join(_dir(home, sid), "turns.jsonl"))
    last = turns[-1] if turns else {}
    since = str(last.get("time") or "")
    root = str(s.get("rootStep") or "")
    root_text = ""
    if root and _parent(s):
        # a step its parent's list holds no more, plans.leave, is read from the words the worker started on
        st = None if s.get("rootLeft") else plans.step_of(plans.load(home, _parent(s)), root)
        root_text = (st or {}).get("content", "") or plans.load(home, sid).get("rootText", "")
    if not root_text:
        return None
    for nid, title, m in others_marks:
        if str(m.get("time") or "") < since:
            continue
        if s.get("unstaled") and str(m.get("time") or "") <= str(s.get("unstaled")):
            continue                                  # it re-based onto this note already
        if plans.bears(m.get("claim"), root_text):
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
    claim = (f"replaces: \"{_title(s)}\" ({sid}) as a live session. What it left in place stays true: {left}, at "
             f"{heads}. " + findings_of(last) + " Its picture of the tree is "
             f"superseded by \"{title}\": \"{_short(m.get('claim'), 300)}\".")
    row = {"time": now, "claim": claim[:FINDINGS_CHARS + 1600], "source": f"p4-phi, a stale session, anchor v{version}",
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
        self.path = path
        self.lock = path + ".lock"
        self.held = False

    def __enter__(self):
        os.makedirs(os.path.dirname(self.lock), exist_ok=True)
        if time.time() - _GAVE_UP.get(self.lock, 0) < LOCK_STALE_S and os.path.exists(self.lock):
            return self                           # a lock this process already waited out, still there: not again
        end = time.time() + LOCK_WAIT_S
        while True:
            try:
                os.close(os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                self.held = True
                _HOLDS.paths = getattr(_HOLDS, "paths", frozenset()) | {self.path}
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.lock) > LOCK_STALE_S:
                        os.remove(self.lock)
                        continue
                except OSError:
                    continue
                if time.time() > end:
                    _GAVE_UP[self.lock] = time.time()
                    return self                   # never block a hook for good: go on unlocked
                time.sleep(0.02)
            except PermissionError:               # Windows, while another thread or process removes the lock file
                if time.time() > end:
                    _GAVE_UP[self.lock] = time.time()
                    return self
                time.sleep(0.02)
            except OSError:
                return self

    def __exit__(self, *exc):
        if self.held:
            _HOLDS.paths = getattr(_HOLDS, "paths", frozenset()) - {self.path}
            try:
                os.remove(self.lock)
            except OSError:
                pass
        return False


LOCK_WAIT_S = 3.0
LOCK_STALE_S = 10.0
REPLACE_WAIT_S = LOCK_WAIT_S / 3   # a write waits out a reader for well under the lock's wait, so a writer
                                   # waiting on the lock it holds meanwhile never gives up for it


def _pend_archive(home, parent, sid, s, kind):
    """Puts this child on its parent's list for the parent's next message, which stale_text words. Under the parent's
    lock, since two children counted as archived in the same minute would each read-modify-write the parent's
    session.json, and the later write would drop the earlier child."""
    ppath = os.path.join(_dir(home, parent), "session.json")

    def later():                                  # kept on a file of its own, which drain_archive reads later
        _write_json(os.path.join(_dir(home, parent), f"archive-pending-{_safe(sid)}.json"),
                    {"id": sid, "title": _title(s), "kind": kind})
    with locked(ppath) as lk:
        pd = _read_json(ppath) if lk.held else {}
        if not pd:                                # never written unlocked, and a record that reads empty, as while
            later()                               # another writer's os.replace runs on Windows, drops no child
            return
        pend = pd.setdefault("staleChildren", [])
        pend[:] = [x for x in pend if not (isinstance(x, dict) and x.get("id") == sid)]
        pend.append({"id": sid, "title": _title(s), "kind": kind})
        pd["staleTold"] = [x for x in pd.get("staleTold") or [] if x != sid]
        try:
            _write_json(ppath, pd)
        except OSError:                           # the child is already marked retired, so no later run puts it
            later()                               # on the parent: it goes where the next run reads it
            return
    ready_page(home)


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


# a brief that says "report when done" or "archive when done" marks its session to be counted as archived when done
DISPOSABLE = re.compile(r"\b(?:archive(?:d)?|report)\s+(?:it\s+|this session\s+)?when\s+(?:it(?:'s| is)\s+|"
                        r"you(?:'re| are)\s+)?(?:done|finished)\b", re.I)


def commits_between(repo, old, new):
    """The one-line subjects of the commits from `old` to `new` in a repository, newest first, at most 8."""
    if not old or not new or old == new:
        return []
    r = _git(repo, "log", "--format=%h %s", "-8", f"{old}..{new}")
    return [x.strip() for x in r.stdout.splitlines() if x.strip()] if r and r.returncode == 0 else []


def outcome(home, sid, s):
    """What a finished session leaves: the files it changed, its heads, the commits made since its first turn, and
    what is still open."""
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
    still += [f"background task {t.get('id')}, {_short(t.get('description') or t.get('command'), 60)}, running"
              for t in plans.in_flight(s)]
    dirty = uncommitted(files)
    if dirty:
        still.append("uncommitted: " + ", ".join(show(f, base) for f in dirty[:8]))
    return files, heads_, commits, still


def closing_commits(home, sid, s):
    """The commits a session made since its first turn whose messages close an issue with a line such as
    `Closes #N`, oldest first, each as its repository, short sha, subject and issues."""
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
            import issues as issues_mod             # its closing keywords: whole words, never after a negation
            issues = issues_mod.closing_refs(parts[2])
            if issues:
                out.append((path, parts[0], parts[1], issues))
    return out


def stores_of(repo):
    """The stores a change in `repo` touches, as far as p4-phi can see: the store of the repository itself, and of
    the nearest folder above it that holds one, as a marketplace checkout sits inside its project."""
    out, d = [], str(repo or "")
    for _ in range(4):
        store = os.path.join(d, ".claude", "p4")
        if d and os.path.isdir(store) and norm(store) not in out:
            out.append(norm(store))
        up = os.path.dirname(d.rstrip("/\\"))
        if not up or up == d:
            break
        d = up
    return out


OWED_MAX = 6                   # owed items named in one push line


def owed(repos, main="main"):
    """What a change in `repos` still owes before it is pushed, as far as p4-phi can see: the machine branches of a
    store it touches that are behind main, read from the refs already fetched. Nothing is fetched and nothing is
    run."""
    out = []
    for store in dict.fromkeys(s for r in repos for s in stores_of(r)):
        top = _git(store, "rev-parse", "--show-toplevel")
        if not top or top.returncode != 0 or norm(top.stdout.strip()) != norm(store):
            continue                               # the store is not a repository of its own: no machine branches
        refs = _git(store, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin")
        for ref in (refs.stdout.split() if refs and refs.returncode == 0 else []):
            name = ref.removeprefix("origin/")
            if name in ("HEAD", main, "origin") or not ref.startswith("origin/"):
                continue
            n = _git(store, "rev-list", "--count", f"{ref}..origin/{main}")
            behind = int(n.stdout.strip() or 0) if n and n.returncode == 0 and n.stdout.strip().isdigit() else 0
            if behind:
                out.append(f"the machine branch `{name}` of the store {store} is {behind} commit"
                           f"{'s' if behind != 1 else ''} behind {main}: that machine's pull and settings")
    return out


# A worker that writes commits on a branch of its own, in its own git worktree, so its commits are not in the checkout
# its orchestrator lands in until that branch is merged. The branch is read where the worker's own Stop hook runs:
# from git in the worktree its closing commits lie in, else from the app's record of the session, whose `branch` is
# the one the app made with the worktree. Where neither names it, the push line sends the orchestrator to the
# worker's report, since the app's own note of a started session's turn names its branch.

def branch_of(sid, s, repo):
    """The branch of the worktree `repo` a session commits in, '' when nothing names it: the branch checked out
    there, by git, else the `branch` of the app's record of the session."""
    r = _git(repo, "rev-parse", "--abbrev-ref", "HEAD") if repo else None
    name = r.stdout.strip() if r is not None and r.returncode == 0 else ""
    if name and name != "HEAD":
        return name
    archived_in_app(s)                            # makes sure RECORD is set: phi.py hands relay the app's records
    try:
        return str(RECORD(sid).get("branch") or "") if RECORD and str(sid).startswith("local_") else ""
    except Exception:  # noqa: BLE001
        return ""


def worktree_branches(sid, s, commits):
    """The worktrees a finished session's `commits` lie in, each with its branch as branch_of reads it: a linked
    worktree's commits wait on a merge. A commit in a main checkout, which sessions share, is on the branch checked
    out there and names none."""
    import p4conf                                 # main_root: the main checkout a worktree's `.git` file leads to
    out = []
    for repo in dict.fromkeys(c[0] for c in commits):
        main, found = p4conf.main_root(repo) if repo else ("", False)
        if found and norm(os.path.realpath(main)) != norm(os.path.realpath(repo)):
            out.append((repo, branch_of(sid, s, repo)))
    return out


GREEN = re.compile(r"\b(green|passed|passes)\b", re.I)


def green_notes(home, sids, commits):
    """[(sha, claim)] for each of `commits` that a note of one of the sessions `sids` holds green: a note whose
    claim names the commit's hash, by its first seven characters or more, with the word green or passed. Such a note
    is the suite's verdict for that commit, kept where a parent, a checker or a later session reads it, so the
    suite is not run again for a hash it names, ezexe/p4#234."""
    out, seen = [], set()
    claims = [str(n.get("claim") or "") for sid in sids if sid
              for n in _rows(os.path.join(_dir(home, sid), "notes.jsonl"))]
    for _, sha, _, _ in commits:
        short = str(sha or "")[:7].lower()
        if len(short) < 7 or short in seen:
            continue
        for claim in claims:
            if short in claim.lower() and GREEN.search(claim):
                seen.add(short)
                out.append((sha, claim))
                break
    return out


TESTS_NAME = re.compile(r"(?<![a-z])(tests?|ci|checks?)(?![a-z])", re.I)
_FILTERS = ("branches", "branches-ignore", "paths", "paths-ignore", "tags", "tags-ignore")


def _yaml_list(inline, block):
    """The entries of a YAML list given inline as `[a, b]` or one scalar, or as the `- a` lines under its key."""
    inline = inline.strip()
    items = inline.strip("[]").split(",") if inline else [x.strip()[1:] for x in block if x.strip().startswith("-")]
    return [x.strip().strip("'\"") for x in items if x.strip().strip("'\"")]


def _indent(line):
    return len(line) - len(line.lstrip())


def _on_push(text, branch):
    """True when a workflow file's `on:` has it run on every push to `branch`: `push` is among its events with no
    `paths` filter, and its `branches` or `branches-ignore`, where it has one, lets the branch through. A push event
    with only `tags` runs on no branch. Read by indentation, which is how GitHub's own workflows are written."""
    lines = [re.sub(r"(^|\s)#.*$", "", x).rstrip() for x in text.replace("\r\n", "\n").split("\n")]
    lines = [x for x in lines if x.strip()]
    at = next((i for i, x in enumerate(lines) if re.match(r"""^["']?on["']?\s*:""", x)), None)
    if at is None:
        return False
    inline = lines[at].split(":", 1)[1].strip()
    if inline:                                     # `on: push`, `on: [push, pull_request]`
        return not inline.startswith("{") and "push" in _yaml_list(inline, ())
    body = []
    for x in lines[at + 1:]:
        if not x[0].isspace():
            break
        body.append(x)
    if not body:
        return False
    top = _indent(body[0])
    if body[0].strip().startswith("-"):            # the events as a block list
        return "push" in _yaml_list("", [x for x in body if _indent(x) == top])
    got = next((i for i, x in enumerate(body) if _indent(x) == top and re.match(r"push\s*:", x.strip())), None)
    if got is None:
        return False
    if body[got].split(":", 1)[1].strip().strip("{} "):
        return False                               # a flow mapping of filters: not read, so not counted
    sub, keys, cur = [], {}, None
    for x in body[got + 1:]:
        if _indent(x) <= top:
            break
        sub.append(x)
    low = _indent(sub[0]) if sub else 0
    for x in sub:
        m = re.match(r"([\w-]+)\s*:(.*)$", x.strip()) if _indent(x) == low else None
        if m:
            cur = m.group(1)
            keys[cur] = [m.group(2), []]
        elif cur:
            keys[cur][1].append(x)
    got = {k: _yaml_list(*v) for k, v in keys.items() if k in _FILTERS}
    if "paths" in got or "paths-ignore" in got:
        return False
    if "branches" in got:
        return any(fnmatch.fnmatchcase(branch, p.replace("**", "*")) for p in got["branches"])
    if "branches-ignore" in got:
        return not any(fnmatch.fnmatchcase(branch, p.replace("**", "*")) for p in got["branches-ignore"])
    return "tags" not in got and "tags-ignore" not in got


def push_workflows(repos):
    """[(name, file)] for each workflow under `.github/workflows/` of the checkouts `repos` that runs the
    repository's tests on every push to its default branch: one _on_push holds for the default branch of the remote,
    `main` where git names none, and whose name or file name says tests, ci or checks, so a workflow that only
    publishes or releases is never read as the verdict on a push. Empty where a repository holds none, and then a
    local run is the only run."""
    out = []
    for repo in dict.fromkeys(r for r in repos if r and os.path.isdir(r)):
        top = _git(repo, "rev-parse", "--show-toplevel")
        root = top.stdout.strip() if top is not None and top.returncode == 0 and top.stdout.strip() else repo
        ref = _git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        branch = (ref.stdout.strip() if ref is not None and ref.returncode == 0 else "").partition("/")[2]
        if not branch:
            old = _git(repo, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/master")
            new = _git(repo, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main")
            branch = "master" if (old is not None and old.returncode == 0
                                  and not (new is not None and new.returncode == 0)) else "main"
        folder = os.path.join(root, ".github", "workflows")
        for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else ():
            if not f.lower().endswith((".yml", ".yaml")):
                continue
            try:
                with open(os.path.join(folder, f), encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            m = re.search(r"^name\s*:\s*(.+?)\s*$", re.sub(r"(?m)\s#.*$", "", text), re.M)
            name = m.group(1).strip("'\"") if m else os.path.splitext(f)[0]
            if (TESTS_NAME.search(name) or TESTS_NAME.search(os.path.splitext(f)[0])) and _on_push(text, branch) \
                    and (name, f) not in out:
                out.append((name, f))
    return out


def push_text(child_title, child, commits, owes=(), branches=(), green=(), workflows=()):
    """The orchestrator's line: land a finished child's issue-closing commits now, without asking. It has the full
    suite run once, on the commit being pushed, by the orchestrator, as one background command, with the verdict
    kept by `phi.py note` under that commit's hash; with `green`, what green_notes found, it names the note and has
    the suite not run again for that hash, ezexe/p4#234. With `branches`,
    the worktrees those commits lie in and the branch of each, as worktree_branches gives them, it has each branch
    merged into the default branch first, since the commits are on the child's own branch and not in the
    orchestrator's checkout. The line is ezexe's standing word to land green work that closes an issue and says
    so, since by the app's own default a session merges a branch of a session it started only when ezexe says so.
    With `owes`, what the change still owes comes first: finished before the push, or named in the report before
    it. With `workflows`, what push_workflows found, the repository's own workflow runs every test on the push, so
    the line has the checks the task named and the test files of the touched paths run before the push, and that
    workflow's run on the pushed commit read after it, in place of the local run of every test. With none, the line
    is word for word what it was, since a local run is then the only run."""
    named = "; ".join(f"{sha} \"{_short(subj, 80)}\" closes {', '.join(n)} in {repo}" for repo, sha, subj, n in commits)
    owes = [x for x in owes if x]
    first = ""
    if owes:
        first = (" Before that push, this change owes: " + "; ".join(owes[:OWED_MAX])
                 + (f"; and {len(owes) - OWED_MAX} more" if len(owes) > OWED_MAX else "")
                 + ". Finish each first. Where one cannot be finished from here, name it in the report before "
                   "pushing, not after.")
    merge = ""
    if branches:
        where = "; ".join((f"`{b}`" if b else "the branch its report names") + f", in its worktree {repo}"
                          for repo, b in branches)
        merge = (f" Those commits are on that session's own branch, {where}, and not in this session's checkout: "
                 f"merge that branch into the default branch first, in the checkout that holds the default branch. "
                 f"This line is ezexe's standing word to land green work that closes an issue, so it stands in "
                 f"place of the app's default, by which a session merges a branch of a session it started only "
                 f"when ezexe says so.")
    green = [(sha, claim) for sha, claim in green if sha]
    if green:
        suite = ("A note holds " + "; ".join(f"{str(sha)[:12]} green, \"{_short(claim, 120)}\"" for sha, claim in green)
                 + ": do not run the suite again for that hash. Push")
    else:
        suite = ("Run the full suite once, on the commit being pushed, in this session, as one background command, "
                 "and keep its verdict under that commit's hash with `phi.py note \"suite green at <hash>\" --source "
                 "\"<the command>\"`, so no session runs it again for that hash. Once it passes, push")
    after = ""
    workflows = [(n, f) for n, f in workflows if n and f]
    if workflows:
        names = " and ".join(f"`{n}`" for n, _ in workflows)
        one = len(workflows) == 1
        if not green:
            suite = (f"That repository's own workflow {names} runs every test on a push to the default branch, so "
                     f"before the push run only the checks the task named and the test files of the paths the "
                     f"commits touch, in this session. Once they pass, push")
        after = (f" After the push, read the run of {names} on the pushed commit: find {'it' if one else 'each'} "
                 f"with " + " and ".join(f"`gh run list --workflow {f} --commit <the pushed commit's full hash>`"
                                         for _, f in workflows)
                 + f", watch {'it' if one else 'each'} with `gh run watch <run id> --exit-status` as one background "
                   f"command, and keep {'its' if one else 'each'} verdict under that commit's hash with `phi.py "
                   f"note \"workflow {workflows[0][0] if one else '<name>'} green at <hash>\" --source \"gh run "
                   f"watch <run id> --exit-status\"`, so no session reads it again for that hash. Mend what a "
                   f"failed run shows.")
    return (f"phi (p4-phi): \"{child_title}\" `{child}` finished with commits that close issues: {named}. "
            f"Green work that closes an issue is landed at once.{merge} "
            f"{suite} that repository's main, without asking ezexe, and say in one line what was "
            f"{'merged and ' if merge else ''}pushed.{after}{first} A force-push, a "
            f"history rewrite or a deletion still waits on ezexe's go, asked as a `mcp__ccd_turn__wrap_up` question "
            f"whose first button is that go.")


FINDINGS_CHARS = 3000          # of the final report of a child counted as archived, kept in its replaces: note
BARE = re.compile(r"^\W*(?:\w+\s+){0,4}(?:is\s+)?(?:done|finished|complete[d]?)(?:\s+and\s+reported)?\W*$", re.I)


def findings_of(last):
    """The findings of a child counted as archived, from its final turn: the shown-done line, and its report in full
    up to FINDINGS_CHARS, from the turn's earlier messages when the last one only says it is done. Says so when the
    turn left none; never a bare "done"."""
    done = " ".join(str(last.get("done") or "").split())
    report = str(last.get("report") or "").strip()
    said = str(last.get("said") or "").strip()
    if said and (not report or len(report) < 400 or BARE.match(report)):
        report = said
    if BARE.match(report or ""):
        report = ""
    out = f"Shown done: \"{_short(done, 400)}\". " if done and not BARE.match(done) else ""
    if report:
        # a report leads with its result, so the head is kept and the tail cut
        cut = report if len(report) <= FINDINGS_CHARS else report[:FINDINGS_CHARS - 3].rstrip() + "..."
        return out + f"Its findings, from its final report: \"{cut}\"."
    return out + "Its final turn left no report text with findings: read its transcript before relying on it."


def retire_done(home, parent, sid, now, extra="", archived=False):
    """Counts as archived a child whose work is over, one marked `disposable` or one that archived itself: its outcome
    is kept as one replaces: note on its parent, it is left out of what relay.py hands other sessions, the anchors and
    the down-lines, and its parent is told at its next message that it is counted as archived. Returns True when it
    was counted as archived now. With `archived`, the child archived itself in the app before its work was shown
    done: the note says so and names the plan steps it left open."""
    path = os.path.join(_dir(home, sid), "session.json")
    disk = _read_json(path)
    if not parent or not disk or disk.get("doneRetired"):
        return False
    files, heads_, commits, still = outcome(home, sid, disk)
    base = disk.get("cwd") or ""
    turns = _rows(os.path.join(_dir(home, sid), "turns.jsonl"))
    last = turns[-1] if turns else {}
    steps = [x for x in still if x.startswith("step ")]
    how = "it finished, and p4-phi counts it as archived from now."
    if archived:
        how = ("it archived itself before its work was shown done, with "
               + (f"{len(steps)} plan step{'s' if len(steps) != 1 else ''} still open: " + "; ".join(steps) + "."
                  if steps else "no plan step left open."))
    claim = (f"replaces: \"{_title(disk)}\" ({sid}) as a live session: {how} "
             + (extra.strip() + " " if extra else "") + "Changed: " + (", ".join(show(f, base) for f in files[:10]) or "no files")
             + (" ..." if len(files) > 10 else "") + ". Heads: " + (", ".join(heads_) or "none") + ". Commits: "
             + ("; ".join(commits) or "none") + ". Still open: " + ("; ".join(still) or "nothing") + ". "
             + findings_of(last))
    row = {"time": now, "claim": claim[:FINDINGS_CHARS + 2000],
           "source": "p4-phi, a child that archived itself" if archived else "p4-phi, a report-when-done child",
           "kind": "decision", "cliSessionId": ""}
    npath = os.path.join(_dir(home, parent), "notes.jsonl")
    os.makedirs(os.path.dirname(npath), exist_ok=True)
    with open(npath, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    disk["doneRetired"] = {"time": now}
    _write_json(path, disk)
    _pend_archive(home, parent, sid, disk, "done")
    return True


# --- gh ---------------------------------------------------------------------------------------------------------------
#
# The app removes a session's worktree itself, at archive or about 30 days after, and `clean_up_worktrees` removes
# the inactive ones on ezexe's approval, desktop.md, "Keep uncommitted changes when a session is archived", so p4-phi
# names no worktree for removal here. What the app leaves, the merged branch and a worktree a session made itself, is
# upkeep.py's to name where a project turns `phi.upkeep` on. gh is run here for the issue loop.

CMD_META = set('&|<>^%!"()\r\n')         # what cmd.exe reads in a .cmd or .bat file's arguments; no quoting stops it


def gh(args, cwd=None, timeout=GIT_S):
    """gh's CompletedProcess, None when there is no gh or it failed to start or finish. It is the one way p4-phi
    runs gh: the gh P4_PHI_GH names, a `.py` file there run with this Python, else the gh on PATH by the full path
    shutil.which found. A gh.cmd or gh.bat wrapper on Windows is started through cmd.exe, which reads its arguments
    again: a `--body` text goes to it as a `--body-file`, and a call with any other argument holding one of the
    characters cmd.exe acts on is not run, and comes back with exit code 1 and a reason naming them on stderr."""
    import shutil
    import tempfile
    cmd = os.environ.get("P4_PHI_GH") or shutil.which("gh")
    if not cmd:
        return None
    argv = [sys.executable, "-I", "-X", "utf8", cmd] if cmd.endswith(".py") else [cmd]
    args, body = [str(a) for a in args], None
    if cmd.lower().endswith((".cmd", ".bat")):
        if "--body" in args[:-1]:
            k = args.index("--body")
            fd, body = tempfile.mkstemp(prefix="p4-phi-gh-body-", suffix=".md")
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(args[k + 1])
            args[k:k + 2] = ["--body-file", body]
        bad = sorted({c for a in args for c in a} & CMD_META)
        if bad:
            if body:
                os.remove(body)
            shown = " ".join(repr(c) for c in bad)
            return subprocess.CompletedProcess(argv + args, 1, "", f"p4-phi: not run, since gh is the wrapper {cmd} "
                                               f"and cmd.exe would act on {shown} in its arguments")
    try:
        return subprocess.run(argv + args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, cwd=cwd or None)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        if body:
            try:
                os.remove(body)
            except OSError:
                pass


def stale_text(pend):
    """The parent's one line about the children in `pend` that are counted as archived, stale or done; '' for none."""
    pend = [x for x in pend or [] if isinstance(x, dict)]
    if not pend:
        return ""
    out = []
    done = [x for x in pend if x.get("kind") == "done"]
    stale = [x for x in pend if x.get("kind") != "done"]
    if stale:
        names = ", ".join(link_of(x) for x in stale)
        out.append(f"phi (p4-phi): stale, their work superseded by a newer note, their outcome kept as a replaces: "
                   f"note on this session: {names}. {READY_UPKEEP if UPKEEP else READY}")
    if done:
        names = ", ".join(link_of(x) for x in done)
        out.append(f"phi (p4-phi): finished, their outcome kept as a replaces: "
                   f"note on this session: {names}. {READY_UPKEEP if UPKEEP else READY}")
    return "\n".join(out)


# --- counted as archived, then archived in the app --------------------------------------------------------------------
#
# A finished or superseded session is counted as archived by p4-phi at once: the replaces: note on its parent,
# `doneRetired` or `stale` in its session.json, and `gone` true for routing, owned paths, the tree and what relay.py
# hands other sessions from that moment. Its parent is told once, and the sessions the app has not archived yet are
# listed on <home>/phi/ready-to-archive.md. Archiving one in the app is ezexe's: the app asks ezexe on its approval
# card before it archives a session, except in Auto mode and Bypass permissions mode, desktop.md, "Work across
# sessions", and the settings keeper writes no ask rule on the archive tool. Where a project turns `phi.upkeep` on,
# those words go, and upkeep.py hands the session that started a finished, landed session its archive call.

UPKEEP = False                   # phi.project_conf sets it from p4.json phi.upkeep
READY = ("p4-phi counts them as archived from now. Archiving one in the app is ezexe's: the archive tool asks "
         "ezexe on the app's approval card before it runs, except in Auto mode and Bypass permissions mode.")
READY_UPKEEP = ("p4-phi counts them as archived from now, and its upkeep line names the archive call of each once "
                "it is finished and landed.")
BUTTON = ("This session is at the top level of its tree and it is done, so end this turn with `mcp__ccd_turn__wrap_up` "
          "whose first action is the app's `archive`, and a recap of one sentence naming what was done: that puts the "
          "button in this session's next-step box, and ezexe archives it with one press. Write no paragraph asking "
          "for it, and call no archive tool for this session.")
CHILD_DONE = ("This session has a parent session, so it shows no archive button and asks for nothing: report what "
              "was done and end the turn. Call no archive tool.")


def link_of(x):
    """A finished child as a link ezexe can open, written [its title](#its id)."""
    title = str(x.get("title") or x.get("id") or "").replace("[", "(").replace("]", ")")
    return f"[{title}](#{x.get('id')})"


def ready_path(home):
    return os.path.join(home, "phi", "ready-to-archive.md").replace("\\", "/")


def _ready_mark(s):
    """What makes a session ready to archive: its finished mark, or its superseded mark until it is messaged again,
    which _rebase records as the superseded mark's `told`, since a superseded session messaged again is live."""
    st = s.get("stale")
    return s.get("doneRetired") or (st if isinstance(st, dict) and not st.get("told") else None)


def ready_page(home):
    """<home>/phi/ready-to-archive.md: the sessions p4-phi holds as finished or superseded that the app has not
    archived yet, each with what it was and when. Rewritten whenever one is counted as archived or reopened."""
    rows = []
    for sid, s in sorted(_sessions(home).items()):
        mark = _ready_mark(s)
        if not mark or s.get("archived") or archived_in_app(s):
            continue
        when = mark.get("time", "") if isinstance(mark, dict) else ""
        rows.append(f"- \"{_title(s)}\" `{sid}`: {'superseded' if s.get('stale') else 'finished'} {when}".rstrip())
    text = "\n".join(["# Ready to archive", "",
                      "Sessions p4-phi holds as finished or superseded and counts as archived, "
                      "not yet archived in the app.",
                      "The page is made again whenever a session is counted as archived or messaged again, and a "
                      "session archived in the app or live again drops off then.", ""]
                     + (rows or ["None."])) + "\n"
    path = ready_path(home)
    try:                                           # best effort: the page is made again at the next count
        p4conf.write_whole(path, text)
    except OSError:
        pass
    return path


def reopened(home, s, now):
    """A session marked finished or archived that is messaged again: its parent is told once that it is live, so
    the mark does not hide live work, and it leaves the ready-to-archive page."""
    sid, parent = s.get("sessionId"), _parent(s)
    if parent:
        warn(home, parent, f"reopened:{sid}:{now}",
             f"\"{_title(s)}\" `{sid}`, which p4-phi held as finished and counted as archived, was messaged again and "
             f"is reopened: it is a live session once more, so do not count its work as over.")
    ready_page(home)


if __name__ == "__main__":                 # the first commit of the session tree, started by a hook: track-first <home>
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if len(sys.argv) == 3 and sys.argv[1] == "track-first":
        track_first(sys.argv[2])
