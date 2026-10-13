"""partition.py — the p4 layout: one directory per session, two cumulative indexes beside them.

    .claude/p4/                       a git repository of its own, separate from the project's
    .claude/p4/sessions/<s8>/vlds/    the session's VLDS store — every file it writes, its own keyspace (idb/)
    .claude/p4/sessions/<s8>/src/     the session's frags (the src-fragger plugin's), with its own register
    .claude/p4/vindex/                the cumulative VLDS index over every session's store, and the recall config
    .claude/p4/sindex/                the cumulative frag register over every session's src/

A session's store is a whole VLDS store, so every writer — the hooks, record.py, the keyspace's sync and pours —
runs on it unchanged and lands in that session's directory: nothing pours it, nothing dates it, and it is never
removed. Readers that need what other sessions wrote — the owner's rulings and standing rules, the verified claims,
the tombstones, the briefs, the ledger's corrections, the logger's history, the owner voice — read across every
session's store (`expand`); the session-local files (`SESSION_LOCAL`: the dispatch record, the inferences, the
tasks, the pooled recall) are read by their own session only.

A store that is not under `sessions/<s8>/vlds` — a test's temp store, or a flat store not yet migrated — is its
own and only session: `session_stores` returns it alone and `vindex_dir` is the store itself, so every reader keeps
the single-store behaviour there.
"""
import os
import time

SESSIONS = "sessions"
VINDEX = "vindex"
SINDEX = "sindex"
LEGACY = "_legacy"            # the session directory a pre-partition store migrates into
INDEX_FILE = "phi-index.md"
VINDEX_KEYS = "keys.tsv"
SESSION_LOCAL = frozenset({"dispatch.md", "virtual.md", "session-storage.md", "recall-pool.md"})


def short(session):
    """A session's directory name: its id's first eight characters."""
    return (str(session or "").strip() or "unknown")[:8]


def p4_of(store):
    """The p4 root a session store sits in (`<p4>/sessions/<s8>/vlds`), or None for a store outside the layout."""
    s = os.path.normpath(os.path.abspath(store))
    sess = os.path.dirname(s)
    if os.path.basename(s) == "vlds" and os.path.basename(os.path.dirname(sess)) == SESSIONS:
        return os.path.dirname(os.path.dirname(sess))
    return None


def partitioned(store):
    return p4_of(store) is not None


def session_store(p4, session):
    return os.path.join(p4, SESSIONS, short(session), "vlds")


def session_src(p4, session):
    return os.path.join(p4, SESSIONS, short(session), "src")


def session_of(store):
    """The session directory's name a store belongs to, or None outside the layout."""
    return os.path.basename(os.path.dirname(os.path.normpath(os.path.abspath(store)))) if partitioned(store) else None


def session_stores(store):
    """Every session's store, oldest-modified first, this one included — or [store] outside the layout."""
    p4 = p4_of(store)
    if p4 is None:
        return [store]
    root = os.path.join(p4, SESSIONS)
    found = []
    try:
        for n in os.listdir(root):
            d = os.path.join(root, n, "vlds")
            if os.path.isdir(d):
                found.append(d)
    except OSError:
        pass
    own = os.path.normcase(os.path.normpath(os.path.abspath(store)))
    if own not in {os.path.normcase(os.path.normpath(d)) for d in found}:
        found.append(store)
    return sorted(found, key=lambda d: (os.path.getmtime(d) if os.path.exists(d) else float("inf"), d))


def label(store, fname):
    """How a reader names a file: `<s8>/<fname>` inside the layout, the bare name outside it."""
    s = session_of(store)
    return f"{s}/{fname}" if s else fname


def expand(store, fname):
    """[(store, label)] — the stores a read of `fname` covers: this session's alone for a session-local file,
    every session's for the rest."""
    base = os.path.basename(fname)
    stores = [store] if base in SESSION_LOCAL else session_stores(store)
    return [(s, label(s, base)) for s in stores]


def paths(store, fname):
    """[(path, label)] for every existing copy of `fname` a read covers."""
    return [(os.path.join(s, os.path.basename(fname)), lb) for s, lb in expand(store, fname)
            if os.path.exists(os.path.join(s, os.path.basename(fname)))]


def vindex_dir(store):
    p4 = p4_of(store)
    return os.path.join(p4, VINDEX) if p4 else store


def sindex_dir(store):
    p4 = p4_of(store)
    return os.path.join(p4, SINDEX) if p4 else None


def config_index(store):
    """The index whose `## recall` section rules the recall — the cumulative one in vindex/ inside the layout (a
    new session's own index starts without it), the store's own outside."""
    v = os.path.join(vindex_dir(store), INDEX_FILE)
    return v if os.path.exists(v) else os.path.join(store, INDEX_FILE)


HOT_NAMES = ("local-storage.md", "index.md", "data-store.md", "ledger.md", "tombstones.md", "virtual.md",
             "session-storage.md", "logger.md", "briefs.md", "dispatch.md")
VINDEX_KEYS_HEAD = ("# vindex — the cumulative VLDS index: every session store's keyspace line, the session's directory "
                    "first; derived, never a ruling (rebuilt at every turn close)\n")
VINDEX_SESSIONS_HEAD = "# vindex sessions — session\tentries\tbytes\tlast-write\ttitle\n"


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def _title(store):
    """The title a session store's .sessions ledger recorded last, or ''."""
    try:
        with open(os.path.join(store, ".sessions"), encoding="utf-8") as f:
            lines = [l.rstrip("\n").split(" ", 3) for l in f if l.strip()]
    except OSError:
        return ""
    return lines[-1][3] if lines and len(lines[-1]) > 3 else ""


def build_vindex(store):
    """Rebuild <p4>/vindex/keys.tsv (every session store's idb/keys.tsv record line, prefixed with its session's
    directory) and <p4>/vindex/sessions.tsv (one line per session: hot entries, bytes, last write, title) — the
    cumulative index a reader uses to find which session holds an entry before it opens that session's store. The
    recall config, vindex/phi-index.md, is a ruling and is never touched here. Returns a one-line report, or '' outside
    the layout."""
    p4 = p4_of(store)
    if p4 is None:
        return ""
    vdir = os.path.join(p4, VINDEX)
    os.makedirs(vdir, exist_ok=True)
    keys, rows, total = [VINDEX_KEYS_HEAD], [VINDEX_SESSIONS_HEAD], 0
    for s in session_stores(store):
        name = os.path.basename(os.path.dirname(s))
        n, size, last = 0, 0, 0.0
        for f in HOT_NAMES:
            path = os.path.join(s, f)
            if os.path.exists(path):
                with open(path, encoding="utf-8", errors="replace") as fh:
                    n += sum(1 for l in fh if l.startswith("- "))
                size += os.path.getsize(path)
                last = max(last, os.path.getmtime(path))
        kpath = os.path.join(s, "idb", "keys.tsv")
        if os.path.exists(kpath):
            with open(kpath, encoding="utf-8", errors="replace") as fh:
                for l in fh:
                    if l.strip() and not l.startswith("#"):
                        keys.append(f"{name}\t{l.rstrip(chr(10))}\n")
                        total += 1
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(last)) if last else "-"
        rows.append(f"{name}\t{n}\t{size}\t{stamp}\t{_title(s)}\n")
    _write(os.path.join(vdir, VINDEX_KEYS), "".join(keys))
    _write(os.path.join(vdir, "sessions.tsv"), "".join(rows))
    return f"vindex: {len(rows) - 1} session store(s), {total} keyspace line(s) indexed"


def homed_dir(dirpath, p4_tail):
    """True when `dirpath` is a session store: `<p4>/sessions/<s8>/vlds`, `p4_tail` the p4 root's normalized tail
    (os.sep + .claude + os.sep + p4)."""
    d = os.path.normcase(os.path.normpath(dirpath))
    if d.endswith(p4_tail + os.sep + VINDEX):       # the recall config, vindex/phi-index.md, is the owner's to edit
        return True
    sess = os.path.dirname(d)
    return (os.path.basename(d) == "vlds" and os.path.basename(os.path.dirname(sess)) == SESSIONS
            and os.path.dirname(os.path.dirname(sess)).endswith(p4_tail))
