#!/usr/bin/env python3
"""idb.py — the VLDS store's keyspace: Chromium's IndexedDB indexing, rebuilt in plain text, in place of the
φ-register's placement arithmetic.

Deterministic and judgment-free, in the phi.py mold: it derives, places, verifies and reports; it never decides what
deserves keeping, and it never deletes what the owner wrote. The operator judges which entries are cold; this script
places them. Design and sources: investigations/2026-09-28-indexeddb-keyspace-in-place-of-the-phi-register.md.

The register of active context does not move: the hot files, phi.py barrier / pool / standing, recall-pool.md and
the index's ## recall section read exactly as before. What moves is everything that leaves the hot files:

  idb/keys.tsv      the keyspace — one sorted, tab-separated line per key; byte order is key order, so `LC_ALL=C sort
                    -c` verifies it and no comparator is carried (the SQLite era's sortable encoding, not LevelDB's
                    idb_cmp1). Derived, rebuildable (`sync --full`), never a ruling.
  idb/runs/         the cold tier — immutable sorted run files, one per pour or compaction (LevelDB's SSTables)
  idb/blobs/        external objects — dispatch records poured whole by the prompt hook, legacy attachments, and any
                    entry past 64 KiB (Chromium's kIDBWrapThreshold)
  idb/journal.tsv   append-only intents: two-phase pours and compactions, the prompt hook's blob pours; recovered at
                    the next pass (Chromium's recovery journal)
  idb/.sweep-lock   the sweep lock, as arc/.sweep-lock was: session-stamped, stale after 60 minutes

A key line is <object store> TAB <type> TAB <key> TAB <field=value> ..., with the types
  00           metadata — per store (object store '@'): schema, synced, next-run, earliest-compaction, sweep-cursor,
               migrated, migrated-runs, retired; per object store: last-version, key-generator
  01           a record: <time>|<sha8 of the head line>[#n] -> v= sha= at=hot:<line> | at=runs/<run>:<line>, and on a
               cold record id= state=live|freed [ts=]; the line carries no value, so it is also the "exists" entry
  03           an external object: <file name> -> blob= bytes= sha= [rows=] [from=]
  30:by-kind   and up: an index entry, <index key>|<primary key> -> v=; live only while v equals the record's (LevelDB's
               lazy index deletion), dropped by the next sync otherwise (its tombstone sweeper)

Subcommands (every writer takes the lock; every reader validates what it reads):
  sync        re-derive the hot tier: an unchanged block keeps its version, a changed one takes last-version + 1 and
              fresh index lines, a vanished one drops; stale index lines swept; cold records marked freed from the
              tombstones; blobs registered; torn commits recovered first. --full rebuilds from the files alone.
              Bounded: past --budget-s the next object store waits for the next round (the sweep cursor).
  light       the turn-close pass the Stop hook runs: sync, then the light classes — another session's virtual entries
              expired and poured, the logger past its budget poured down to three quarters — then a compaction when
              due. Any count pours: no position has to open.
  pour        a judged pour placed: FILE:L1,L2 ... names the entries the sweep moment scored cold, by head line;
              two-phase — journal, write the run, the verify-pour gate, commit the keyspace, trim the hot file. A root
              (a local-storage.md or index.md entry the read barrier reads LIVE) is refused unless --archive is passed.
  archive     /vlds:gc archive, on the owner's word alone: every entry of every hot object store poured through the
              pour's own path, LIVE roots included, nothing exempt; the hot tier left empty for the next session, the
              cold tier reached only by /vlds:recall. --dry prints the counts and writes nothing.
  compact     merge an object store's small runs (4 or more, or 2 or more when due): verify-merge first, exact
              duplicates collapsed, nothing freed ever dropped.
  migrate     the gentle migration from the φ-register: arc/ imported verbatim (ids kept), every entry and blob
              verified, the keyspace committed, arc/ moved aside to arc.phi-retired/ (kept; its disposal is the
              owner's). --dry plans and verifies in a temporary directory; --shadow is idb-control's one-line verdict.
  rollback    undo a migration at any point: entries poured since back to their hot files, arc/ back, the φ
              index back with index-engine: phi, idb/ removed — refused only if an archived entry was edited since.
  get / range / find   point, range and index reads, each validated against the record's version and sha.
  blob / blobs   an external object's text (a poured dispatch record, a legacy attachment), refused unless it is
              registered and still hashes to the sha the keyspace recorded; and the listing of what is registered.
  check       the keyspace scans, plus the store-level scans phi.py check keeps (duplication, liveness, conformance,
              stray, the hot budgets and the φ pressure ratio); exit 1 = corruption.
  engine      which engine runs this store, from the index's `index-engine:` and what is on disk.
  pool-stamp / pool-diff   the recall pool's snapshot of the hot tier, and after a compact what was written since.
  digest      the SessionStart digest lines.

Stages — `index-engine:` in the index's ## recall section, a ruling; absent, DEFAULT_ENGINE (idb-migrate-gentle):
  phi                 the φ-register runs; this script is idle — the stage a store names to stay on the φ-register
  idb-control         the φ-register runs; the turn close adds a shadow migration's verdict, writing nothing
  idb-new-stores      a store with no φ trace starts on the keyspace; a φ store stays φ
  idb-migrate-gentle  a new store starts on the keyspace; a φ store migrates at a turn close once its φ check is clean
  idb                 the same, the stage at which the φ code paths retire
A store with idb/keys.tsv is on the keyspace whatever the setting says; `rollback` is the one way back.
"""

import argparse
import contextlib
import datetime
import hashlib
import io
import os
import random
import re
import shutil
import sys
import tempfile
import time
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import phi  # noqa: E402 — the barrier's parser, its masks and the store-level scans, shared rather than copied

SCHEMA = "1"
IDB = "idb"
KEYS = "keys.tsv"
JOURNAL = "journal.tsv"
RUNS = "runs"
BLOBS = "blobs"
LOCK = ".sweep-lock"
POOL_STAMP = "pool-stamp.tsv"
ROLLBACK_MARK = "rollback-returned"   # idb/rollback-returned: a rollback's hot-file returns are made; resume, never redo
PENDING = "pending"             # idb/pending/<record>: a dispatch pour in flight — one marker file per pour, since the
                                # prompt hook holds no lock and a shared journal rewritten under the lock would lose it
POOL_FILE = "recall-pool.md"
INDEX_FILE = "phi-index.md"
RETIRED = "arc.phi-retired"
NOW_FMT = "%Y-%m-%d %H:%M"
LOCK_STALE_S = 3600
WRAP_BYTES = 64 * 1024          # Chromium's kIDBWrapThreshold: a block past it lives in a blob, the run holds a marker
RUN_TARGET = 64 * 1024          # a compaction splits its output at an entry boundary past this size; smaller is "small"
COMPACT_TRIGGER = 4             # small runs in one object store that force a compaction (LevelDB's level-0 trigger)
COMPACT_DUE_MIN = 2             # small runs a due compaction needs
COMPACT_DELAY_DAYS = (1.0, 3.0)  # the next earliest-compaction, uniform — Chromium's per-bucket jitter
SYNC_BUDGET_S = 20.0            # a sync's wall-clock budget; past it the next object store waits for the next round
BLOB_PENDING_GRACE_S = 600      # a blob pour younger than this may still be in flight in another session's prompt hook
LOW_WATER = 0.75                # the logger pours down to this fraction of its budget
MIGRATE_SPACE_FACTOR = 2.5      # Chromium's migration margin: the disk must hold this multiple of the old store
ENGINES = ("phi", "idb-control", "idb-new-stores", "idb-migrate-gentle", "idb")
DEFAULT_ENGINE = "idb-migrate-gentle"
KEYS_HEAD = ("# vlds keyspace — derived from the hot files, the runs and the blobs; never a ruling "
             "(idb.py sync --full rebuilds it)\n")
INDEX_HEAD = ("# VLDS Store — Index\n\nDerived — the hot table is rewritten at every move; the ## recall section and "
              "the budget column are rulings.")

# hot file -> id prefix; the object store is the file's name without .md
OBJECT_STORES = {"local-storage.md": "ls", "index.md": "ix", "data-store.md": "ds", "ledger.md": "le",
                 "tombstones.md": "ts", "virtual.md": "vr", "session-storage.md": "ss", "logger.md": "lg",
                 "briefs.md": "br"}
ROOT_FILES = {"local-storage.md", "index.md"}   # where a LIVE entry is a root: the owner's rulings and standing rules
PREFIX_OS = {p: f[:-3] for f, p in OBJECT_STORES.items()}
DEFAULT_BUDGET = {"local-storage.md": 21, "index.md": 21, "data-store.md": 34, "ledger.md": 21,
                  "tombstones.md": 21, "virtual.md": 13, "session-storage.md": 13, "logger.md": 34,
                  "briefs.md": 21}
HOT_ORDER = ["local-storage.md", "index.md", "data-store.md", "ledger.md", "tombstones.md", "virtual.md",
             "session-storage.md", "logger.md", "briefs.md", "dispatch.md"]
REC_ORDER = ("v", "sha", "at", "id", "state", "ts")
BLOB_ORDER = ("blob", "bytes", "sha", "rows", "from")
ID_RE = re.compile(r"^id: ([a-z]{2})-(\d{4,})( \(tombstoned\))?\s*$")
FACT_ID_ANY_RE = re.compile(r"\b([a-z]{2}-\d{4,})\b")
INDEX_TYPE_RE = re.compile(r"^(\d\d):[a-z-]+$")
RUN_NAME_RE = re.compile(r"^([a-z][a-z-]*)-(\d{6,})\.md$")
SEG_NAME_RE = re.compile(r"^arc-(\d+)-([A-Za-z0-9]+)\.md$")
POURED_DISPATCH_RE = re.compile(r"^dispatch-\d{8}-\d{6}-[0-9A-Za-z-]{1,12}\.md$")
# the light classes' rules, the same as normalize.py's
MINTED_RE = re.compile(r"^  minted:\s*session\s+([0-9A-Za-z-]+)", re.M)
DISPOSITION_RE = re.compile(r"^  disposition:\s*pending\s*$")
SUFFIX_RE = re.compile(r"#\d+$")
WRAP_RE = re.compile(r"^\(wrapped: (\S+) sha=([0-9a-f]+)\)$")

Block = namedtuple("Block", "line1 start end head text field value fields")
RunEntry = namedtuple("RunEntry", "line1 id_line rid pk body")
JournalLine = namedtuple("JournalLine", "raw when op jid state detail")


class PourError(Exception):
    pass


class MigrateError(Exception):
    pass


# ─── files ──────────────────────────────────────────────────────────────────────────────────────────────

def read_raw(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def read_text(path):
    """A file's text with its line endings normalized to LF — the one reading every derivation hashes."""
    return read_raw(path).replace("\r\n", "\n")


def write_text(path, text, crlf=False):
    """Write through a temporary file and a rename, so a reader never sees half a file."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\n", "\r\n") if crlf else text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def sha(text, n=12):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def file_sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]


_ROOT = {}      # store -> the directory idb_path() resolves to, when a migration builds beside the real one


def idb_path(store, *parts):
    return os.path.join(_ROOT.get(os.path.abspath(store), os.path.join(store, IDB)), *parts)


def rel_path(store, rel):
    """A keyspace path (`runs/x.md`, `blobs/dispatch/y.md`, always forward slashes) as a path on this disk."""
    return idb_path(store, *rel.split("/"))


@contextlib.contextmanager
def idb_root(store, path):
    key = os.path.abspath(store)
    old = _ROOT.get(key)
    _ROOT[key] = path
    try:
        yield
    finally:
        if old is None:
            _ROOT.pop(key, None)
        else:
            _ROOT[key] = old


def clock(now):
    return datetime.datetime.strptime(now[:16], NOW_FMT)


# ─── locks ──────────────────────────────────────────────────────────────────────────────────────────────

def lock_holder(path):
    """(holder, age in seconds) of a lock file, or (None, 0)."""
    if not os.path.exists(path):
        return None, 0
    try:
        holder = (read_text(path).split() or ["?"])[0]
        return holder, time.time() - os.path.getmtime(path)
    except OSError:
        return "?", 0


def take_lock(path, session):
    """The sweep lock, phi.py's semantics — session-stamped, stale after 60 minutes — with an exclusive create, so two
    sessions racing for a free lock cannot both win it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    stamp = f"{session} {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(stamp)
        return True, "granted"
    except FileExistsError:
        holder, age = lock_holder(path)
        if holder != session and age < LOCK_STALE_S:
            return False, f"lock held by {holder} ({int(age)} s old)"
        # a stale or own lock is taken over under a guard only one process can create; holding it, the lock is read
        # again and replaced whole — never moved, so a lock another process just made is never taken from under it
        guard = path + ".takeover"
        try:
            gfd = os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            with contextlib.suppress(OSError):
                if time.time() - os.path.getmtime(guard) > 60:     # a takeover a crash abandoned
                    os.remove(guard)
            return False, "lock taken over by another session a moment ago"
        os.close(gfd)
        try:
            holder, age = lock_holder(path)
            if holder is not None and holder != session and age < LOCK_STALE_S:
                return False, f"lock held by {holder} ({int(age)} s old)"
            write_text(path, stamp)
            return True, f"superseding {'own' if holder == session else 'stale'} lock ({holder}, {int(age)} s)"
        finally:
            with contextlib.suppress(OSError):
                os.remove(guard)


def release_lock(path, session):
    holder, _age = lock_holder(path)
    if holder == session:
        with contextlib.suppress(OSError):
            os.remove(path)


# ─── the engine ─────────────────────────────────────────────────────────────────────────────────────────

def index_text(store):
    p = os.path.join(store, INDEX_FILE)
    return read_text(p) if os.path.exists(p) else ""


def recall_value(text, key):
    """A key's value under the index's `## recall` section, or None."""
    in_recall = False
    for l in text.split("\n"):
        if l.startswith("## "):
            in_recall = l[3:].strip().lower() == "recall"
            continue
        if in_recall:
            m = re.match(rf"^{re.escape(key)}:\s*(.*)$", l.strip())
            if m:
                return m.group(1).strip()
    return None


def engine_setting(store):
    """(setting, named) — the index's `index-engine:`, or DEFAULT_ENGINE when it names none it knows."""
    v = (recall_value(index_text(store), "index-engine") or "").lower()
    return (v, True) if v in ENGINES else (DEFAULT_ENGINE, False)


def has_runs(store):
    d = idb_path(store, RUNS)
    return os.path.isdir(d) and any(RUN_NAME_RE.match(n) for n in os.listdir(d))


def store_state(store):
    """'idb' (a keyspace, or runs whose keys.tsv is gone), 'phi' (a register line in the index, or anything in arc/
    but its lock), 'empty'."""
    if os.path.exists(idb_path(store, KEYS)) or has_runs(store):
        return "idb"
    if re.search(r"^register:", index_text(store), re.M):
        return "phi"
    arc = os.path.join(store, "arc")
    if os.path.isdir(arc) and any(f != LOCK for f in os.listdir(arc)):
        return "phi"
    return "empty"


def resolve(store):
    """(engine, setting, state) — engine: 'idb' (the keyspace runs), 'phi' (the φ-register runs), 'shadow' (φ runs and
    a shadow migration reports), 'migrate' (a φ store owed its migration). Chromium's rollout stages, one per setting."""
    setting, _named = engine_setting(store)
    state = store_state(store)
    if state == "idb":
        engine = "idb"
    elif setting == "phi":
        engine = "phi"
    elif setting == "idb-control":
        engine = "shadow"
    elif setting == "idb-new-stores":
        engine = "idb" if state == "empty" else "phi"
    else:
        engine = "migrate" if state == "phi" else "idb"
    return engine, setting, state


# ─── the hot tier ───────────────────────────────────────────────────────────────────────────────────────

def parse_block(text):
    """(field, value, fields) for an entry block, the way phi.py's hot_entries reads one: a logger bullet's field is
    'log'; the continuation fields' first occurrence wins."""
    lines = text.split("\n")
    m = phi.HOT_HEAD_RE.match(lines[0])
    field, value = (m.group(1), m.group(2)) if m else ("log", lines[0][2:] if lines[0].startswith("- ") else lines[0])
    fields = {}
    for l in lines[1:]:
        fm = phi.HOT_FIELD_RE.match(l)
        if fm and fm.group(1) not in fields:
            fields[fm.group(1)] = fm.group(2)
    return field, value, fields


def hot_blocks(store, fname):
    """[Block] — every column-0 '- ' head after the header separator with its two-space continuation lines, exactly
    the blocks phi.py barrier reads; None when the file is absent."""
    path = os.path.join(store, fname)
    if not os.path.exists(path):
        return None
    lines = read_text(path).split("\n")
    try:
        start = lines.index("---") + 1
    except ValueError:
        start = 0
    out, i = [], start
    while i < len(lines):
        if not lines[i].startswith("- "):
            i += 1
            continue
        j = i + 1
        while j < len(lines) and lines[j].startswith("  "):
            j += 1
        text = "\n".join(lines[i:j])
        field, value, fields = parse_block(text)
        out.append(Block(i + 1, i, j, lines[i], text, field, value, fields))
        i = j
    return out


def entry_time(head, field, value, fields):
    for src in (fields.get("time", ""), value if field == "log" else "", head):
        m = phi.STAMP_RE.search(src or "")
        if m:
            return m.group(1)
    return "0000-00-00 00:00"


def base_pk(head, field, value, fields):
    """<time>|<sha8 of the head line> — derived, so the hot files carry nothing new; a continuation edit is an update,
    a head rewrite a delete plus an insert."""
    return f"{entry_time(head, field, value, fields)}|{sha(head.rstrip(), 8)}"


def block_pk(b):
    return base_pk(b.head, b.field, b.value, b.fields)


def assign_pks(blocks, taken):
    """One primary key per block: its base key, `#2`, `#3` ... for a repeat, never one a cold record holds."""
    seen, out = {}, []
    for b in blocks:
        base = block_pk(b)
        n = seen.get(base, 0)
        while True:
            n += 1
            pk = base if n == 1 else f"{base}#{n}"
            if pk not in taken:
                break
        seen[base] = n
        out.append(pk)
    return out


def budgets(store):
    """{hot file: entry budget} — the index's hot table budget column (a ruling), else the defaults."""
    out = dict(DEFAULT_BUDGET)
    idx = phi.parse_index(store)
    for row in (idx or {}).get("hot", []):
        try:
            out[row[0]] = int(row[4])
        except (ValueError, IndexError):
            pass
    return out


def clean_key(k):
    k = re.sub(r"[|\t\r\n]", "_", str(k)).strip()
    return k or "-"


def index_keys(os_, field, value, fields, rid=None):
    """[(type, index key)] — the user indexes an entry lands in, each serving a reader the store already has: by-kind
    the standing set, by-status the status fields, by-owner-words the barrier's same-words mask as a join, by-source
    the UNOWNED call on a claim, by-session another session's inference, by-fact-id the handles tombstones cite."""
    out = [("30:by-kind", phi.entry_kind(os_ + ".md", field, fields))]
    if os_ == "local-storage" and fields.get("status", "").strip():
        out.append(("31:by-status", fields["status"].split()[0].upper()))
    if os_ == "virtual" and fields.get("disposition", "").strip():
        out.append(("31:by-status", fields["disposition"].split()[0].upper()))
    if os_ in ("local-storage", "tombstones"):
        words = phi.norm_text(fields.get("owner-words", ""))
        if words:
            out.append(("32:by-owner-words", sha(words, 8)))
    if os_ == "data-store":
        sourced = fields.get("verified", "").strip() or fields.get("source", "").strip()
        out.append(("33:by-source", "sourced" if sourced else "unsourced"))
    if os_ == "virtual":
        ids = phi.SESSION_ID_RE.findall(fields.get("minted", "").lower())
        if ids:
            out.append(("34:by-session", ids[0]))
    if rid:
        out.append(("35:by-fact-id", rid))
    return [(t, clean_key(k)) for t, k in out]


def rewrite_lines(store, fname, replacements):
    """Replace whole lines of a hot file by 0-based index, keeping its line endings."""
    path = os.path.join(store, fname)
    raw = read_raw(path)
    crlf = "\r\n" in raw
    lines = raw.replace("\r\n", "\n").split("\n")
    for i, l in replacements.items():
        lines[i] = l
    write_text(path, "\n".join(lines), crlf=crlf)


def trim_blocks(store, fname, blocks):
    """Remove blocks from a hot file, each with the blank line before it, keeping its line endings — refused when a
    block is no longer where the parse found it."""
    path = os.path.join(store, fname)
    raw = read_raw(path)
    crlf = "\r\n" in raw
    lines = raw.replace("\r\n", "\n").split("\n")
    drop = set()
    for b in blocks:
        if "\n".join(lines[b.start:b.end]) != b.text:
            raise PourError(f"{fname}: the block at line {b.line1} moved before the trim")
        drop.update(range(b.start, b.end))
        if b.start > 0 and lines[b.start - 1] == "":
            drop.add(b.start - 1)
    write_text(path, "\n".join(l for i, l in enumerate(lines) if i not in drop), crlf=crlf)


def expired_line(now):
    return f"  disposition: expired (turn close {now}; minted by another session, its turn over)"


# ─── the cold tier ──────────────────────────────────────────────────────────────────────────────────────

def parse_run(path):
    """(header, [RunEntry]) — a ```yaml header, then entries between column-0 '---' lines: an `id:` line, a `key:`
    line, a blank line, the verbatim body (a φ segment's grammar with one line more)."""
    lines = read_text(path).split("\n")
    header, entries = {}, []
    first = next((i for i, l in enumerate(lines) if l.strip()), None)
    if first is None:
        return header, entries
    if lines[first] != "```yaml":
        raise ValueError(f"{os.path.basename(path)}: header is not a ```yaml fence")
    close = next((i for i in range(first + 1, len(lines)) if lines[i] == "```"), None)
    if close is None:
        raise ValueError(f"{os.path.basename(path)}: unterminated header fence")
    for l in lines[first + 1:close]:
        m = re.match(r"^([A-Za-z-]+):\s*(.*)$", l)
        if m:
            header[m.group(1)] = m.group(2)
    blocks, cur = [], None
    for idx in range(close + 1, len(lines)):
        if lines[idx] == "---":
            if cur is not None:
                blocks.append(cur)
            cur = []
        elif cur is not None:
            cur.append((idx, lines[idx]))
    if cur is not None:
        blocks.append(cur)
    for blk in blocks:
        while blk and blk[0][1] == "":
            blk.pop(0)
        while blk and blk[-1][1] == "":
            blk.pop()
        if not blk:
            continue
        id_idx, id_line = blk[0]
        m = ID_RE.match(id_line)
        rid = f"{m.group(1)}-{m.group(2)}" if m else ""
        rest, pk = blk[1:], ""
        if rest and rest[0][1].startswith("key: "):
            pk = rest[0][1][len("key: "):]
            rest = rest[1:]
        while rest and rest[0][1] == "":
            rest.pop(0)
        entries.append(RunEntry(id_idx + 1, id_line, rid, pk, "\n".join(t for _i, t in rest)))
    return header, entries


def render_run(name, os_, entries, now, session8, via):
    """(text, [line of each entry's id line]) for entries [(id line, key, body)] in key order."""
    body = "".join(f"---\n{id_line}\nkey: {pk}\n\n{b}\n" for id_line, pk, b in entries)
    keys = f"{entries[0][1]} .. {entries[-1][1]}" if entries else "-"
    head = ["```yaml", f"run: {name[:-3]}", f"object-store: {os_}", f"entries: {len(entries)}", f"keys: {keys}",
            f"written: {now} by {session8} via {via}", f"sha: {sha(body)}", "```"]
    line1s, n = [], len(head) + 1
    for _id_line, _pk, b in entries:
        line1s.append(n + 1)
        n += 4 + b.count("\n") + 1
    return "\n".join(head) + "\n" + body, line1s


def unwrap(store, body):
    """A run entry's body, or the blob a wrap marker names."""
    m = WRAP_RE.match(body)
    if not m:
        return body
    p = rel_path(store, m.group(1))
    return read_text(p) if os.path.exists(p) else body


class RunCache:
    """Runs parsed once per pass: {run name: {line of the id line: RunEntry}}."""

    def __init__(self, store):
        self.store, self.runs = store, {}

    def entry(self, at):
        name, _sep, line = at[len("runs/"):].rpartition(":")
        if name not in self.runs:
            p = rel_path(self.store, f"{RUNS}/{name}")
            try:
                self.runs[name] = {e.line1: e for e in parse_run(p)[1]} if os.path.exists(p) else {}
            except (ValueError, OSError):
                self.runs[name] = {}
        try:
            return self.runs[name].get(int(line))
        except ValueError:
            return None


def blob_fields(path, rel, sub, origin=None):
    lines = read_text(path).split("\n") if path.endswith(".md") else []
    if "---" in lines:
        lines = lines[lines.index("---") + 1:]
    rows = sum(1 for l in lines if l.startswith("- fingerprint:" if sub == "dispatch" else "- "))
    f = {"blob": rel, "bytes": str(os.path.getsize(path)), "sha": file_sha(path), "rows": str(rows)}
    if origin:
        f["from"] = origin
    return f


# ─── the keyspace ───────────────────────────────────────────────────────────────────────────────────────

class Keyspace:
    def __init__(self):
        self.meta = {}      # (scope, name) -> value; scope '@' is the store
        self.records = {}   # (object store, primary key) -> {field: value}
        self.blobs = {}     # (object store, file name) -> {field: value}
        self.index = {}     # (object store, type, "<index key>|<primary key>") -> {"v": ...}

    @classmethod
    def fresh(cls):
        ks = cls()
        ks.meta[("@", "schema")] = SCHEMA
        ks.meta[("@", "next-run")] = "1"
        return ks

    @classmethod
    def load(cls, path):
        """(keyspace, [problem]) — a problem is an unparseable, unknown, duplicate or out-of-order line."""
        ks, errors, prev = cls(), [], None
        for n, raw in enumerate(read_text(path).split("\n"), 1):
            if not raw or raw.startswith("#"):
                continue
            if prev is not None and raw < prev:
                errors.append(f"line {n} out of order")
            prev = raw
            parts = raw.split("\t")
            if len(parts) < 4:
                errors.append(f"line {n} has fewer than four fields")
                continue
            os_, typ, key = parts[:3]
            if typ == "00":
                ks.meta[(os_, key)] = "\t".join(parts[3:])
                continue
            fields, bad = {}, False
            for p in parts[3:]:
                k, sep, v = p.partition("=")
                if not sep:
                    bad = True
                    break
                fields[k] = v
            if bad:
                errors.append(f"line {n} has a field without '='")
                continue
            if typ == "01":
                target, k2 = ks.records, (os_, key)
            elif typ == "03":
                target, k2 = ks.blobs, (os_, key)
            elif INDEX_TYPE_RE.match(typ) and int(typ[:2]) >= 30:
                target, k2 = ks.index, (os_, typ, key)
            else:
                errors.append(f"line {n} has an unknown type {typ!r}")
                continue
            if k2 in target:
                errors.append(f"line {n} repeats a key")
            target[k2] = fields
        return ks, errors

    def dump(self):
        def fmt(fields, order):
            keys = [k for k in order if k in fields] + [k for k in fields if k not in order]
            return "\t".join(f"{k}={fields[k]}" for k in keys)
        lines = [f"{s}\t00\t{name}\t{v}" for (s, name), v in self.meta.items()]
        lines += [f"{o}\t01\t{pk}\t{fmt(f, REC_ORDER)}" for (o, pk), f in self.records.items()]
        lines += [f"{o}\t03\t{k}\t{fmt(f, BLOB_ORDER)}" for (o, k), f in self.blobs.items()]
        lines += [f"{o}\t{t}\t{k}\t{fmt(f, ('v',))}" for (o, t, k), f in self.index.items()]
        lines.sort()
        return KEYS_HEAD + "".join(l + "\n" for l in lines)

    def cold(self, os_=None):
        return {k: r for k, r in self.records.items()
                if r.get("at", "").startswith("runs/") and (os_ is None or k[0] == os_)}


def save_keys(store, ks):
    os.makedirs(idb_path(store), exist_ok=True)
    write_text(idb_path(store, KEYS), ks.dump())


def load_keys(store):
    """(keyspace, how) — 'loaded', 'new', or 'rebuilt …' when keys.tsv cannot be read as a sorted keyspace."""
    p = idb_path(store, KEYS)
    if not os.path.exists(p):
        if has_runs(store):
            return rebuild(store), "rebuilt from the files (keys.tsv was missing)"
        return Keyspace.fresh(), "new"
    ks, errors = Keyspace.load(p)
    if errors:
        return rebuild(store, ks), f"rebuilt from the files ({errors[0]}{'…' if len(errors) > 1 else ''})"
    return ks, "loaded"


def rebuild(store, old=None):
    """A keyspace from the files alone: every run entry a cold record (a key held twice goes to the newest run, the
    older entry kept as history), every blob registered; the hot tier is the caller's sync. Versions restart."""
    ks = Keyspace.fresh()
    old_meta = old.meta if old is not None else {}
    for name in ("migrated", "migrated-runs", "retired"):
        if ("@", name) in old_meta:
            ks.meta[("@", name)] = old_meta[("@", name)]
    runs_dir = idb_path(store, RUNS)
    names = []
    for n in os.listdir(runs_dir) if os.path.isdir(runs_dir) else []:
        m = RUN_NAME_RE.match(n)
        if m:
            names.append((int(m.group(2)), n))
    names.sort()
    ks.meta[("@", "next-run")] = str(max((num for num, _n in names), default=0) + 1)
    gens, seen = {}, {}
    for num, name in names:
        os_ = RUN_NAME_RE.match(name).group(1)
        try:
            _h, entries = parse_run(os.path.join(runs_dir, name))
        except (ValueError, OSError):
            continue
        for e in entries:
            body = unwrap(store, e.body)
            field, value, fields = parse_block(body)
            pk = e.pk or base_pk(body.split("\n", 1)[0], field, value, fields)
            seen[(os_, pk)] = (name, e, body, field, value, fields)
            if e.rid:
                prefix, number = e.rid.split("-", 1)
                gens[os_] = max(gens.get(os_, 0), int(number))
    versions = {}
    for (os_, pk), (name, e, body, field, value, fields) in sorted(seen.items()):
        versions[os_] = versions.get(os_, 0) + 1
        v = str(versions[os_])
        rec = {"v": v, "sha": sha(body), "at": f"runs/{name}:{e.line1}", "state": "live"}
        if e.rid:
            rec["id"] = e.rid
        ks.records[(os_, pk)] = rec
        for typ, ikey in index_keys(os_, field, value, fields, e.rid or None):
            ks.index[(os_, typ, f"{ikey}|{pk}")] = {"v": v}
    for os_, n in versions.items():
        ks.meta[(os_, "last-version")] = str(n)
    for os_, n in gens.items():
        ks.meta[(os_, "key-generator")] = str(n)
    if old is not None:     # a blob's origin (from=arc) outlives a rebuild, so a rollback still tells imports from pours
        for k, f in old.blobs.items():
            if os.path.exists(rel_path(store, f.get("blob", ""))):
                ks.blobs[k] = dict(f)
    if ("@", "migrated") not in ks.meta and os.path.isdir(os.path.join(store, RETIRED)):
        ks.meta[("@", "migrated")] = "(marker rebuilt from the retired arc directory)"
        ks.meta[("@", "retired")] = RETIRED
    return ks


# ─── the journal ────────────────────────────────────────────────────────────────────────────────────────

def journal_append(store, op, jid, state, detail=""):
    os.makedirs(idb_path(store), exist_ok=True)
    with open(idb_path(store, JOURNAL), "a", encoding="utf-8", newline="\n") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{op}\t{jid}\t{state}\t{detail}\n")
        f.flush()
        os.fsync(f.fileno())


def journal_read(store):
    p = idb_path(store, JOURNAL)
    if not os.path.exists(p):
        return []
    out = []
    for raw in read_text(p).split("\n"):
        if not raw.strip():
            continue
        parts = raw.split("\t")
        parts += [""] * (5 - len(parts))
        out.append(JournalLine(raw, parts[0], parts[1], parts[2], parts[3], "\t".join(parts[4:])))
    return out


def journal_open(lines):
    """{(op, id): its latest line} for every intent not yet done or aborted."""
    latest = {}
    for jl in lines:
        latest[(jl.op, jl.jid)] = jl
    return {k: v for k, v in latest.items() if v.state not in ("done", "aborted")}


def journal_compact(store):
    """Keep only the intents still open — the log shrinks once its sorted tables hold what it recorded."""
    p = idb_path(store, JOURNAL)
    if not os.path.exists(p):
        return
    lines = journal_read(store)
    open_ = journal_open(lines)
    write_text(p, "".join(jl.raw + "\n" for jl in lines if (jl.op, jl.jid) in open_))


def journal_age(jl):
    try:
        return time.time() - time.mktime(time.strptime(jl.when, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return float("inf")


def pending_open(store, name):
    """Mark a dispatch pour in flight: idb/pending/<record name>, written before the copy."""
    d = idb_path(store, PENDING)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
        f.flush()
        os.fsync(f.fileno())


def pending_close(store, name):
    """The pour is whole — the copy verified and dispatch.md reseeded: its marker goes."""
    with contextlib.suppress(OSError):
        os.remove(idb_path(store, PENDING, name))


def pending_markers(store):
    """{record name: age in seconds} for every dispatch pour still marked in flight."""
    d = idb_path(store, PENDING)
    out = {}
    for n in os.listdir(d) if os.path.isdir(d) else []:
        with contextlib.suppress(OSError):
            out[n] = time.time() - os.path.getmtime(os.path.join(d, n))
    return out


def settle_pending(store, ks=None):
    """Every dispatch pour marked in flight past the grace: its copy removed when dispatch.md still holds its rows (the
    reseed never ran), kept otherwise; the marker closed either way. Returns (notes, young) — `young` the markers still
    inside the grace, which may be another session's pour in flight and are never touched."""
    notes, young = [], []
    for name, age in sorted(pending_markers(store).items()):
        if age < BLOB_PENDING_GRACE_S:
            young.append(name)
            continue
        path = rel_path(store, f"{BLOBS}/dispatch/{name}")
        if dispatch_holds(store, path):
            with contextlib.suppress(OSError):
                os.remove(path)
            if ks is not None:
                ks.blobs.pop(("dispatch", name), None)
            notes.append(f"recovered a torn dispatch pour: blobs/dispatch/{name} removed, its rows still in dispatch.md")
        else:
            notes.append(f"recovered a dispatch pour whose marker outlived it: blobs/dispatch/{name} kept and registered")
        pending_close(store, name)
    return notes, young


def dispatch_holds(store, blob):
    """True when dispatch.md still carries every row of a poured copy — the reseed never happened."""
    p = os.path.join(store, "dispatch.md")
    if not os.path.exists(p) or not os.path.exists(blob):
        return False
    have = {l for l in read_text(p).split("\n") if l.startswith("- ")}
    rows = [l for l in read_text(blob).split("\n") if l.startswith("- ")]
    return bool(rows) and all(r in have for r in rows)


def finish_trim(store, ks, run):
    """A committed pour whose trim never ran: every block still hot with its record's sha is trimmed; a block the owner
    edited since keeps the edit — its cold record is dropped from the keyspace and the run keeps the old text as
    history. (trimmed, kept hot)."""
    by_file = {}
    for (os_, pk), r in ks.records.items():
        if r.get("at", "").startswith(f"runs/{run}:"):
            by_file.setdefault(os_, []).append((pk, r))
    trimmed = kept = 0
    for os_, items in by_file.items():
        blocks = hot_blocks(store, os_ + ".md") or []
        drop, used = [], set()
        for pk, r in items:
            base = SUFFIX_RE.sub("", pk)
            same = [b for b in blocks if b.line1 not in used and block_pk(b) == base]
            match = next((b for b in same if sha(b.text) == r.get("sha")), None)
            if match is not None:
                drop.append(match)
                used.add(match.line1)
                trimmed += 1
            elif same:
                del ks.records[(os_, pk)]
                kept += 1
        if drop:
            trim_blocks(store, os_ + ".md", drop)
    return trimmed, kept


def recover(store, ks):
    """Settle every torn commit the journal still holds open; returns one line per recovery."""
    notes = []
    referenced = lambda run: any(r.get("at", "").startswith(f"runs/{run}:") for r in ks.records.values())  # noqa: E731
    for (op, jid), jl in journal_open(journal_read(store)).items():
        if op == "pour":
            if not referenced(jid):
                if jl.state == "pending":
                    for rel in [f"{RUNS}/{jid}"] + [w for w in jl.detail.partition("wrapped=")[2].split(",") if w]:
                        with contextlib.suppress(OSError):
                            os.remove(rel_path(store, rel))
                    journal_append(store, op, jid, "aborted", "recovered: the keyspace never named it")
                    notes.append(f"recovered a torn pour: {jid} discarded before its commit, its entries still hot")
                else:
                    journal_append(store, op, jid, "done", "recovered: nothing names it any longer")
            else:
                trimmed, kept = finish_trim(store, ks, jid)
                save_keys(store, ks)            # before the journal calls it done: a later failure must not lose it
                journal_append(store, op, jid, "done", f"recovered: {trimmed} trimmed, {kept} kept hot")
                notes.append(f"recovered a torn pour: {jid} committed, its trim finished ({trimmed} trimmed"
                             + (f", {kept} edited since and kept hot — the run keeps the old text" if kept else "")
                             + ")")
        elif op == "compact":
            d = dict(kv.split("=", 1) for kv in jl.detail.split(";") if "=" in kv)
            children = [c for c in d.get("children", "").split(",") if c]
            parents = [c for c in d.get("parents", "").split(",") if c]
            if jl.state == "pending" and not any(referenced(c) for c in children):
                for c in children:
                    with contextlib.suppress(OSError):
                        os.remove(rel_path(store, f"{RUNS}/{c}"))
                journal_append(store, op, jid, "aborted", "recovered: the keyspace never named its output")
                notes.append(f"recovered a torn compaction: {jid} discarded before its commit")
            else:
                for p in parents:
                    if not referenced(p):
                        with contextlib.suppress(OSError):
                            os.remove(rel_path(store, f"{RUNS}/{p}"))
                journal_append(store, op, jid, "done", "recovered: parents collected")
                notes.append(f"recovered a torn compaction: {jid} committed, its parents collected")
    settled, _young = settle_pending(store, ks)
    if settled:
        save_keys(store, ks)
    return notes + settled


# ─── sync ───────────────────────────────────────────────────────────────────────────────────────────────

def new_rep():
    return {"updated": 0, "inserted": 0, "dropped": 0, "swept": [], "registered": [], "freed": 0, "deferred": []}


def sync_store(store, ks, fname, rep):
    """One object store's hot tier re-derived: unchanged blocks keep their version and index lines, a changed or new
    one takes last-version + 1 and fresh index lines, a vanished one drops; cold records stand."""
    os_ = fname[:-3]
    blocks = hot_blocks(store, fname) or []
    cold = {pk for (o, pk), r in ks.records.items() if o == os_ and r.get("at", "").startswith("runs/")}
    old_hot = {pk: r for (o, pk), r in ks.records.items() if o == os_ and not r.get("at", "").startswith("runs/")}
    last = max([int(ks.meta.get((os_, "last-version"), "0") or 0)]
               + [int(r.get("v", 0) or 0) for (o, _pk), r in ks.records.items() if o == os_])
    fresh = {}
    for pk, b in zip(assign_pks(blocks, cold), blocks):
        h = sha(b.text)
        old = old_hot.get(pk)
        if old is not None and old.get("sha") == h:
            v = int(old.get("v", 0) or 0)
        else:
            last += 1
            v = last
            rep["updated" if old is not None else "inserted"] += 1
        fresh[pk] = (v, h, b)
    for pk in old_hot:
        del ks.records[(os_, pk)]
        if pk not in fresh:
            rep["dropped"] += 1
    for k in [k for k in ks.index if k[0] == os_ and k[2].split("|", 1)[-1] in old_hot]:
        del ks.index[k]
    for pk, (v, h, b) in fresh.items():
        ks.records[(os_, pk)] = {"v": str(v), "sha": h, "at": f"hot:{b.line1}"}
        for typ, ikey in index_keys(os_, b.field, b.value, b.fields):
            ks.index[(os_, typ, f"{ikey}|{pk}")] = {"v": str(v)}
    if last > 0:
        ks.meta[(os_, "last-version")] = str(last)


def register_blobs(store, ks, rep, skip=()):
    """Every file under blobs/ the keyspace does not name yet, registered — except one a pending pour still holds."""
    bdir = idb_path(store, BLOBS)
    if not os.path.isdir(bdir):
        return
    for sub in sorted(os.listdir(bdir)):
        sp = os.path.join(bdir, sub)
        if not os.path.isdir(sp):
            continue
        for name in sorted(os.listdir(sp)):
            rel = f"{BLOBS}/{sub}/{name}"
            if name.endswith(".tmp") or (sub, name) in ks.blobs or rel in skip:
                continue
            if os.path.isfile(os.path.join(sp, name)):
                ks.blobs[(sub, name)] = blob_fields(os.path.join(sp, name), rel, sub)
                rep["registered"].append(f"{sub}/{name}")


def mark_freed(store, ks, rep=None, cache=None):
    """A cold record's state, derived at every pass from every tombstone, hot or cold: masked by the barrier's own rule
    (phi.tombstone_hit — the same owner-words, or a head within its freed:), named by id in a tombstone's freed: or
    swept:, or carrying the φ era's `(tombstoned)` annotation → freed, the tombstone's key in ts=; otherwise live.
    Nothing freed is ever removed from a run: the marker is the whole of the free."""
    cache = cache or RunCache(store)
    masks, named = [], {}
    texts = []
    tomb_blocks = hot_blocks(store, "tombstones.md") or []
    cold_t = ks.cold("tombstones")
    for pk, b in zip(assign_pks(tomb_blocks, {pk for (_o, pk) in cold_t}), tomb_blocks):
        texts.append((pk, b.text))
    for (_o, pk), r in cold_t.items():
        e = cache.entry(r["at"])
        if e is not None:
            texts.append((pk, unwrap(store, e.body)))
    for pk, text in texts:
        field, value, fields = parse_block(text)
        if field != "freed":
            continue
        masks.append((pk, phi.norm_text(value), phi.norm_text(fields.get("owner-words", "")), fields.get("time", "")))
        for fid in FACT_ID_ANY_RE.findall(" ".join([value, fields.get("swept", ""), fields.get("freed", "")])):
            named.setdefault(fid, pk)
    flips = 0
    for (os_, pk), r in ks.records.items():
        if not r.get("at", "").startswith("runs/") or os_ == "tombstones":
            continue
        e = cache.entry(r["at"])
        state, ts = "live", None
        if e is not None:
            field, value, fields = parse_block(unwrap(store, e.body))
            hit = phi.tombstone_hit(value, fields, masks)
            if hit:
                state, ts = "freed", hit[0]
            elif r.get("id") in named:
                state, ts = "freed", named[r["id"]]
            elif "(tombstoned)" in e.id_line:
                state, ts = "freed", "annotation"
        if (r.get("state"), r.get("ts")) != (state, ts):
            flips += 1
        r["state"] = state
        if ts:
            r["ts"] = ts
        else:
            r.pop("ts", None)
    if rep is not None:
        rep["freed"] = sum(1 for r in ks.records.values() if r.get("state") == "freed")
        rep["freed_flips"] = flips


def sweep_index(ks, before, rep):
    """The tombstone sweeper, folded into the rewrite: an index line whose record is gone or whose version is not the
    record's is dropped; `before` is the index as the pass found it, so the report names what left."""
    for k in list(ks.index):
        os_, _typ, ikey = k
        rec = ks.records.get((os_, ikey.split("|", 1)[-1]))
        if rec is None or rec.get("v") != ks.index[k].get("v"):
            del ks.index[k]
    rep["swept"] = sorted(k for k in before if k not in ks.index)


def sync(store, ks, now, budget_s=SYNC_BUDGET_S, only=None, rep=None, cache=None):
    """The hot tier re-derived into `ks` in place, in rounds: object stores in order from the sweep cursor, the next one
    left for the next pass once the budget is spent (at least one always runs); then blobs, freed marks, the sweep."""
    rep = rep if rep is not None else new_rep()
    before = set(ks.index)
    names = sorted(OBJECT_STORES)
    if only is not None:
        order = [f for f in names if f[:-3] in only]
    else:
        cur = ks.meta.get(("@", "sweep-cursor"), "-")
        k = next((i for i, f in enumerate(names) if f[:-3] == cur), 0)
        order = names[k:] + names[:k]
    t0 = time.monotonic()
    finished = True
    for i, fname in enumerate(order):
        if only is None and i > 0 and time.monotonic() - t0 >= budget_s:
            ks.meta[("@", "sweep-cursor")] = fname[:-3]
            rep["deferred"] = [f[:-3] for f in order[i:]]
            finished = False
            break
        sync_store(store, ks, fname, rep)
    if only is None and finished:
        ks.meta[("@", "sweep-cursor")] = "-"
    pending = {f"{BLOBS}/dispatch/{n}" for n in pending_markers(store)}
    register_blobs(store, ks, rep, skip=pending)
    mark_freed(store, ks, rep, cache)
    sweep_index(ks, before, rep)
    ks.meta[("@", "synced")] = now
    return rep


def sync_line(rep):
    parts = [f"{rep[k]} {k}" for k in ("inserted", "updated", "dropped") if rep[k]]
    if rep["swept"]:
        parts.append(f"{len(rep['swept'])} stale index line{'s' if len(rep['swept']) != 1 else ''} swept")
    if rep["registered"]:
        parts.append(f"{len(rep['registered'])} blob{'s' if len(rep['registered']) != 1 else ''} registered")
    if rep.get("freed_flips"):
        parts.append(f"{rep['freed_flips']} cold record{'s' if rep['freed_flips'] != 1 else ''} re-marked by the tombstones")
    if rep["deferred"]:
        parts.append(f"{len(rep['deferred'])} object store(s) left for the next round ({', '.join(rep['deferred'])})")
    return "synced: " + (", ".join(parts) if parts else "no change")


# ─── pour ───────────────────────────────────────────────────────────────────────────────────────────────

def do_pour(store, ks, spec, now, session8, via, expire=None):
    """The judged pour and the light classes' alike, two-phase: the expiry rewrite (so the run says why an entry left),
    a sync of the stores touched, journal `pending`, the runs and any wrapped blobs written, the verify-pour gate, the
    keyspace committed (the commit point: records point at the runs), journal `committed`, the hot files trimmed,
    journal `done`. A gate that fails removes what it wrote and raises; a crash is the next pass's recovery."""
    for fname, repl in (expire or {}).items():
        if repl:
            rewrite_lines(store, fname, repl)
    sync(store, ks, now, only={f[:-3] for f in spec})
    plans = []
    next_run = int(ks.meta.get(("@", "next-run"), "1") or 1)
    for fname in sorted(spec):
        if fname not in OBJECT_STORES:
            raise PourError(f"{fname}: not a hot file that pours")
        os_, prefix = fname[:-3], OBJECT_STORES[fname]
        blocks = {b.line1: b for b in (hot_blocks(store, fname) or [])}
        at_line = {int(r["at"][4:]): pk for (o, pk), r in ks.records.items() if o == os_ and r.get("at", "").startswith("hot:")}
        chosen = []
        for l1 in sorted(set(spec[fname])):
            if l1 not in blocks:
                raise PourError(f"{fname}: line {l1} is not an entry head (heads at {sorted(blocks)})")
            chosen.append((at_line[l1], blocks[l1]))
        chosen.sort(key=lambda c: c[0])
        gen = int(ks.meta.get((os_, "key-generator"), "0") or 0)
        entries, wrapped = [], []
        for pk, b in chosen:
            gen += 1
            rid = f"{prefix}-{gen:04d}"
            body = b.text
            if len(body.encode("utf-8")) > WRAP_BYTES:
                rel = f"{BLOBS}/{os_}/{rid}.md"
                wrapped.append((rel, body))
                body = f"(wrapped: {rel} sha={sha(b.text)})"
            entries.append({"id_line": f"id: {rid}", "pk": pk, "body": body, "rid": rid, "block": b})
        plans.append({"fname": fname, "os": os_, "run": f"{os_}-{next_run:06d}.md", "entries": entries,
                      "wrapped": wrapped, "gen": gen})
        next_run += 1
    written = []
    try:
        os.makedirs(idb_path(store, RUNS), exist_ok=True)
        for p in plans:
            journal_append(store, "pour", p["run"], "pending", "wrapped=" + ",".join(rel for rel, _b in p["wrapped"]))
            for rel, body in p["wrapped"]:
                path = rel_path(store, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                write_text(path, body)
                written.append(path)
            path = rel_path(store, f"{RUNS}/{p['run']}")
            if os.path.exists(path):
                raise PourError(f"{p['run']} already exists")
            text, line1s = render_run(p["run"], p["os"], [(e["id_line"], e["pk"], e["body"]) for e in p["entries"]],
                                      now, session8, via)
            write_text(path, text)
            written.append(path)
            p["line1s"], p["text"] = line1s, text
        for p in plans:     # the verify-pour gate: every poured block verbatim in its run, a wrapped one in its blob
            for e in p["entries"]:
                b = e["block"]
                m = WRAP_RE.match(e["body"])
                if m:
                    if read_text(rel_path(store, m.group(1))) != b.text:
                        raise PourError(f"verify-pour: {p['fname']}:{b.line1} differs in its blob")
                    continue
                for piece in phi.split_span_bodies(b.text.split("\n")):
                    if piece.strip() and piece not in p["text"]:
                        raise PourError(f"verify-pour: {p['fname']}:{b.line1} not verbatim in {p['run']}")
    except Exception:
        for path in written:
            with contextlib.suppress(OSError):
                os.remove(path)
        for p in plans:
            journal_append(store, "pour", p["run"], "aborted", "a gate failed; nothing written stays")
        raise
    for p in plans:         # the commit point: the keyspace names the runs
        for e, l1 in zip(p["entries"], p["line1s"]):
            r = ks.records[(p["os"], e["pk"])]
            ks.records[(p["os"], e["pk"])] = {"v": r["v"], "sha": r["sha"], "at": f"runs/{p['run']}:{l1}",
                                              "id": e["rid"], "state": "live"}
            ks.index[(p["os"], "35:by-fact-id", f"{e['rid']}|{e['pk']}")] = {"v": r["v"]}
        ks.meta[(p["os"], "key-generator")] = str(p["gen"])
    ks.meta[("@", "next-run")] = str(next_run)
    save_keys(store, ks)
    for p in plans:
        journal_append(store, "pour", p["run"], "committed")
    for p in plans:
        trim_blocks(store, p["fname"], [e["block"] for e in p["entries"]])
        journal_append(store, "pour", p["run"], "done")
    return plans


def pour_summary(plans):
    n = sum(len(p["entries"]) for p in plans)
    counts = ", ".join(f"{len(p['entries'])} {p['fname']}" for p in plans)
    return n, f"poured {n} ({counts}) into {', '.join(p['run'] for p in plans)}"


def plan_light(store, session8, now):
    """({file: [head lines]}, {file: {line index: rewritten line}}) — the light classes, counted, never scored."""
    spec, expire = {}, {}
    for b in hot_blocks(store, "virtual.md") or []:
        m = MINTED_RE.search(b.text)
        if m and m.group(1)[:8] != session8:
            spec.setdefault("virtual.md", []).append(b.line1)
            for k, l in enumerate(b.text.split("\n")):
                if DISPOSITION_RE.match(l):
                    expire.setdefault("virtual.md", {})[b.start + k] = expired_line(now)
    lb = hot_blocks(store, "logger.md") or []
    budget = budgets(store).get("logger.md", DEFAULT_BUDGET["logger.md"])
    if len(lb) > budget:
        spec["logger.md"] = [b.line1 for b in lb[:len(lb) - int(budget * LOW_WATER)]]
    return spec, expire


def log_move(store, now, headline, parts, run_by):
    """One logger entry per move, in the logger's tagged-bullet shape; nothing when there is no logger."""
    path = os.path.join(store, "logger.md")
    if not os.path.exists(path):
        return
    raw = read_raw(path)
    entry = f"\n- `[gc]` {now} — **{headline}.** " + "; ".join(parts) + f". {run_by.rstrip('.')}.\n"
    write_text(path, raw.replace("\r\n", "\n") + entry, crlf="\r\n" in raw)


# ─── compaction ─────────────────────────────────────────────────────────────────────────────────────────

def next_compaction(store, now):
    """now + a uniform 1–3 days, seeded by the store and the clock: jittered across stores, repeatable in a test."""
    rng = random.Random(f"{os.path.abspath(store)}|{now}")
    return (clock(now) + datetime.timedelta(days=rng.uniform(*COMPACT_DELAY_DAYS))).strftime(NOW_FMT)


def compact_store(store, ks, os_, parents, now, session8):
    """Merge one object store's runs: every entry kept verbatim — a key held twice (history) stays twice, only exact
    duplicates collapse — sorted by key, split at entry boundaries past RUN_TARGET; verify-merge before the commit,
    the parents deleted after it."""
    entries = []
    for name in parents:
        _h, es = parse_run(rel_path(store, f"{RUNS}/{name}"))
        entries += [(e.id_line, e.pk, e.body, name, e.line1) for e in es]
    uniq, alias, seen = [], {}, {}
    for ent in entries:
        k = ent[:3]
        if k not in seen:
            seen[k] = len(uniq)
            uniq.append(ent)
        alias[(ent[3], ent[4])] = seen[k]
    for key, r in ks.records.items():       # every record a parent holds must land somewhere, before anything is written
        at = r.get("at", "")
        name, _sep, line = at[len("runs/"):].rpartition(":")
        if at.startswith("runs/") and name in parents and (name, int(line)) not in alias:
            raise PourError(f"{key[0]} {key[1]} names {at}, which holds no entry")
    order = sorted(range(len(uniq)), key=lambda i: (uniq[i][1], parents.index(uniq[i][3]), uniq[i][4]))
    groups, cur, size = [], [], 0
    for i in order:
        n = len(f"---\n{uniq[i][0]}\nkey: {uniq[i][1]}\n\n{uniq[i][2]}\n".encode("utf-8"))
        if cur and size + n > RUN_TARGET:
            groups.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += n
    if cur:
        groups.append(cur)
    next_run = int(ks.meta.get(("@", "next-run"), "1") or 1)
    names = []
    for _g in groups:
        names.append(f"{os_}-{next_run:06d}.md")
        next_run += 1
    taken = [n for n in names if os.path.exists(rel_path(store, f"{RUNS}/{n}"))]
    if taken:
        raise PourError(f"{taken[0]} already exists — the run counter is behind the files; `idb.py sync --full`")
    jid = f"compact-{names[0][:-3]}"
    journal_append(store, "compact", jid, "pending", f"children={','.join(names)};parents={','.join(parents)}")
    where, texts, written = {}, {}, []
    try:
        for name, g in zip(names, groups):
            text, line1s = render_run(name, os_, [uniq[i][:3] for i in g], now, session8,
                                      "a compaction (scripts/idb.py compact)")
            write_text(rel_path(store, f"{RUNS}/{name}"), text)
            written.append(rel_path(store, f"{RUNS}/{name}"))
            texts[name] = text
            for i, l1 in zip(g, line1s):
                where[i] = (name, l1)
        for ent in entries:                 # verify-merge: every parent entry verbatim in its child
            name, _l1 = where[alias[(ent[3], ent[4])]]
            if f"{ent[0]}\nkey: {ent[1]}\n\n{ent[2]}\n" not in texts[name]:
                raise PourError(f"verify-merge: {ent[3]}:{ent[4]} not verbatim in {name}")
    except Exception:
        for path in written:
            with contextlib.suppress(OSError):
                os.remove(path)
        journal_append(store, "compact", jid, "aborted", "a gate failed; nothing written stays")
        raise
    for r in ks.records.values():
        at = r.get("at", "")
        name, _sep, line = at[len("runs/"):].rpartition(":")
        if at.startswith("runs/") and name in parents:
            cn, cl = where[alias[(name, int(line))]]
            r["at"] = f"runs/{cn}:{cl}"
    ks.meta[("@", "next-run")] = str(next_run)
    save_keys(store, ks)
    journal_append(store, "compact", jid, "committed")
    for name in parents:
        with contextlib.suppress(OSError):
            os.remove(rel_path(store, f"{RUNS}/{name}"))
    journal_append(store, "compact", jid, "done")
    return names


def compact(store, ks, now, session8, force=False, only=None):
    """Compaction when it is owed: an object store with COMPACT_TRIGGER small runs, or COMPACT_DUE_MIN once
    earliest-compaction has passed; the next earliest time set whenever a due pass ran (Chromium's two clocks, one here:
    no process outlives a hook). Returns one line per object store compacted."""
    out = []
    due_at = ks.meta.get(("@", "earliest-compaction"))
    if not due_at:
        ks.meta[("@", "earliest-compaction")] = next_compaction(store, now)
    due = force or bool(due_at and now >= due_at)
    runs_dir = idb_path(store, RUNS)
    groups = {}
    for name in sorted(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else []:
        m = RUN_NAME_RE.match(name)
        if m and os.path.getsize(os.path.join(runs_dir, name)) < RUN_TARGET:
            groups.setdefault(m.group(1), []).append((int(m.group(2)), name))
    for os_, rs in sorted(groups.items()):
        if only is not None and os_ not in only:
            continue
        if len(rs) >= COMPACT_TRIGGER or (due and len(rs) >= COMPACT_DUE_MIN):
            parents = [n for _num, n in sorted(rs)]
            names = compact_store(store, ks, os_, parents, now, session8)
            out.append(f"compacted {os_}: {len(parents)} runs → {', '.join(names)}")
    if due:
        ks.meta[("@", "earliest-compaction")] = next_compaction(store, now)
    return out


# ─── the index file ─────────────────────────────────────────────────────────────────────────────────────

def entry_count(path):
    """Column-0 '- ' lines after the header separator — the hot table's `live`, counted as phi.py counts it."""
    lines = read_text(path).split("\n")
    try:
        start = lines.index("---") + 1
    except ValueError:
        start = 0
    return sum(1 for l in lines[start:] if l.startswith("- "))


def rewrite_index(store, now, session8, via, detail="", poured=()):
    """phi-index.md in the keyspace's shape: the head kept, the register line, positions and epochs retired, the hot
    table recounted (its budget column a ruling, kept; at-sweep moved for the files just poured), the ## recall section
    and any section the owner added kept verbatim, the updated: line rewritten."""
    path = os.path.join(store, INDEX_FILE)
    raw = read_raw(path) if os.path.exists(path) else ""
    crlf = "\r\n" in raw
    head, sections, order, cur = [], {}, [], None
    for l in raw.replace("\r\n", "\n").split("\n"):
        if l.startswith("## "):
            cur = l[3:].strip()
            order.append(cur)
            sections[cur] = [l]
        elif l.startswith("updated:"):
            continue
        elif cur is None:
            if not l.startswith("register:"):
                head.append(l)
        else:
            sections[cur].append(l)
    old = {}
    for l in sections.get("hot", []):
        cells = [c.strip() for c in l.strip("|").split("|")]
        if l.startswith("|") and cells and cells[0] not in ("file", "") and not set(cells[0]) <= {"-", " ", ":"}:
            old[cells[0]] = cells
    rows = []
    for fname in HOT_ORDER:
        p = os.path.join(store, fname)
        if not os.path.exists(p):
            continue
        live = entry_count(p)
        o = old.get(fname)
        at = str(live) if fname in poured or not o or len(o) < 3 else o[2]
        budget = o[4] if o and len(o) > 4 else str(DEFAULT_BUDGET.get(fname, "floor"))
        rows.append(f"| {fname} | {live} | {at} | {os.path.getsize(p)} | {budget} | — | ok |")
    out = ["\n".join(head).rstrip("\n") or INDEX_HEAD, "", "## hot", "",
           "| file | live | at-sweep | bytes | budget | watermark | pressure |",
           "| --- | --- | --- | --- | --- | --- | --- |"] + rows
    for name in order:
        if name in ("hot", "positions", "epochs"):
            continue
        body = sections[name]
        while body and not body[-1].strip():
            body = body[:-1]
        out += [""] + body
    out += ["", f"updated: {now} by {session8} via {via}" + (f" — {detail}" if detail else ""), ""]
    write_text(path, "\n".join(out), crlf=crlf)


# ─── light ──────────────────────────────────────────────────────────────────────────────────────────────

def finish_migration(store, ks, now, session8):
    """A migration's steps after its commit, each idempotent, so a crash between them is finished by the next pass: the
    φ index saved into arc/, arc/ moved aside, the index rewritten in the keyspace's shape."""
    notes = []
    if not ks.meta.get(("@", "migrated")) or os.path.exists(idb_path(store, ROLLBACK_MARK)):
        return notes
    arc = os.path.join(store, "arc")
    idx = os.path.join(store, INDEX_FILE)
    has_register = bool(re.search(r"^register:", index_text(store), re.M))
    if os.path.isdir(arc) and set(os.listdir(arc)) <= {LOCK}:
        with contextlib.suppress(OSError):      # nothing but a lock: nothing to retire
            os.remove(os.path.join(arc, LOCK))
            os.rmdir(arc)
    if os.path.isdir(arc):
        if has_register and not os.path.exists(os.path.join(arc, INDEX_FILE)):
            shutil.copyfile(idx, os.path.join(arc, INDEX_FILE))
        name = RETIRED
        n = 1
        while os.path.exists(os.path.join(store, name)):
            n += 1
            name = f"{RETIRED}.{n}"
        os.replace(arc, os.path.join(store, name))
        with contextlib.suppress(OSError):
            os.remove(os.path.join(store, name, LOCK))
        ks.meta[("@", "retired")] = name
        notes.append(f"arc/ moved to {name}/ — kept; its disposal is the owner's")
    if has_register:
        rewrite_index(store, now, session8, "the migration to the keyspace (scripts/idb.py migrate)",
                      re.sub(r"^\S+ \S+ by \S+ ", "", ks.meta[("@", "migrated")]))
        notes.append("phi-index.md rewritten — register, positions and epochs retired; ## recall and the budgets kept")
    return notes


def check_verdict(store):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_check(store)
    lines = [l for l in buf.getvalue().split("\n") if l.strip()]
    return lines[-1] if lines else "idb.py check: no output"


def cmd_light(store, session, now, dry=False, budget_s=None):
    """The Stop hook's pass on the keyspace: recover, finish a migration, sync, pour the light classes, compact when
    due, rewrite the index when anything moved; one report line, `turn-close: …`."""
    session8 = session[:8]
    tag = "turn-close"
    if dry:
        spec, _expire = plan_light(store, session8, now)
        print(f"{tag}: dry run — would pour " + (", ".join(f"{len(v)} {k}" for k, v in spec.items()) or "nothing"))
        return 0
    if os.path.exists(idb_path(store, ROLLBACK_MARK)):
        print(f"{tag}: nothing moved — a rollback is mid-way; `idb.py rollback` finishes it")
        return 0
    t0 = time.monotonic()
    budget = budget_s if budget_s is not None else float("inf")

    def spent():
        return time.monotonic() - t0 >= budget
    lockp = idb_path(store, LOCK)
    ok, msg = take_lock(lockp, session)
    if not ok:
        print(f"{tag}: skipped — {msg}")
        return 0
    summary, step = [], "load"
    cache = RunCache(store)
    first = not os.path.exists(idb_path(store, KEYS))
    try:
        ks, how = load_keys(store)
        if how.startswith("rebuilt"):
            summary.append(f"keyspace {how}")
        step = "recover"
        summary += recover(store, ks)
        step = "migration"
        summary += finish_migration(store, ks, now, session8)
        step = "sync"
        rep = sync(store, ks, now, budget_s=min(SYNC_BUDGET_S, max(budget / 3, 1)), cache=cache)
        step = "plan"
        spec, expire = plan_light(store, session8, now)
        plans = []
        if spec and not spent():
            step = "pour"
            plans = do_pour(store, ks, spec, now, session8, "the turn-close light pass (scripts/idb.py light)", expire)
            summary.append(pour_summary(plans)[1])
        elif spec:
            summary.append("the light pour waits for the next turn close (out of time)")
        step = "compact"
        compacted = compact(store, ks, now, session8) if not spent() else []
        summary += compacted
        step = "logger entry"
        if plans or compacted:
            n = pour_summary(plans)[0] if plans else 0
            log_move(store, now, f"Turn-close light pass — {n} pours into the keyspace",
                     ([pour_summary(plans)[1]] if plans else []) + compacted,
                     "Run mechanically by scripts/idb.py light from the Stop hook; every trim after the keyspace commit")
        step = "final sync"
        sync(store, ks, now, budget_s=0 if spent() else SYNC_BUDGET_S, cache=cache)
        save_keys(store, ks)
        if plans or compacted or first or not os.path.exists(os.path.join(store, INDEX_FILE)):
            rewrite_index(store, now, session8, "the turn-close light pass (scripts/idb.py light)",
                          pour_summary(plans)[1] if plans else ("the keyspace started" if first else ""),
                          poured=[p["fname"] for p in plans])
        if first:
            summary.insert(0, f"keyspace started — {len(ks.records)} records indexed")
        journal_compact(store)
    except Exception as e:  # noqa: BLE001 — the report names the step; nothing unverified was deleted
        release_lock(lockp, session)
        print(f"{tag}: stopped at {step} — {type(e).__name__}: {e}")
        return 1
    release_lock(lockp, session)
    if not summary:
        print(f"{tag}: nothing to move ({sync_line(rep)})")
        return 0
    print(f"{tag}: " + "; ".join(summary) + ("; the check waits for the next pass (out of time)" if spent()
                                            else f"; {check_verdict(store)}"))
    return 0


def cmd_sync(store, session, now, full=False, budget_s=SYNC_BUDGET_S):
    lockp = idb_path(store, LOCK)
    ok, msg = take_lock(lockp, session)
    if not ok:
        print(f"sync: skipped — {msg}")
        return 0
    try:
        if full:
            old = Keyspace.load(idb_path(store, KEYS))[0] if os.path.exists(idb_path(store, KEYS)) else None
            ks, how = rebuild(store, old), "rebuilt from the files (--full)"
        else:
            ks, how = load_keys(store)
        notes = recover(store, ks) + finish_migration(store, ks, now, session[:8])
        rep = sync(store, ks, now, budget_s=budget_s)
        save_keys(store, ks)
        journal_compact(store)
    finally:
        release_lock(lockp, session)
    for n in notes:
        print(f"- {n}")
    print(f"sync: keyspace {how}; {sync_line(rep)}")
    for os_, typ, ikey in rep["swept"]:
        print(f"- swept {os_} {typ} {ikey}")
    return 0


def cmd_pour(store, session, now, specs, dry=False, archive=False):
    """The judged pour: the operator's sweep moment names what is cold by head line; this places it — any count.
    A root — a local-storage.md or index.md entry the read barrier reads LIVE — is refused unless `archive` is set,
    so a sweep's naming never pours a LIVE ruling; the archive is the one caller that sets it."""
    session8 = session[:8]
    tag = "archive" if archive else "sweep"
    spec = {}
    for item in specs:
        fname, _sep, lines = item.partition(":")
        try:
            spec.setdefault(fname.strip(), []).extend(int(x) for x in lines.split(",") if x.strip())
        except ValueError:
            print(f"{tag}: refused — {item!r}: head lines must be integers")
            return 1
    masks = phi.tombstone_masks(store)
    for fname, lines in spec.items():
        blocks = {b.line1: b for b in (hot_blocks(store, fname) or [])}
        if fname not in OBJECT_STORES:
            print(f"{tag}: refused — {fname}: not a hot file that pours")
            return 1
        bad = [l for l in lines if l not in blocks]
        if bad:
            print(f"{tag}: refused — {fname}: line {bad[0]} is not an entry head (heads at {sorted(blocks)})")
            return 1
        if not archive and fname in ROOT_FILES:
            for l in lines:
                b = blocks[l]
                if phi.barrier_state(fname, b.field, b.value, b.fields, session, masks)[0] == "LIVE":
                    kind = "ruling" if fname == "local-storage.md" else "rule"
                    print(f"{tag}: refused — {fname}:{l} is a LIVE {kind}, a root; a sweep never pours one "
                          "(only /vlds:gc archive does, through --archive)")
                    return 1
    if dry:
        print(f"{tag}: dry run — would pour " + ", ".join(f"{len(v)} {k}" for k, v in spec.items())
              + "; nothing written")
        return 0
    if archive:
        via = "the archive (/vlds:gc archive), placed by scripts/idb.py archive"
        run_by = "Run on the owner's word by /vlds:gc archive, placed by scripts/idb.py archive"
    else:
        via = "the sweep moment, placed by scripts/idb.py pour"
        run_by = "Scored by the operator's sweep moment, placed and run by scripts/idb.py pour"
    lockp = idb_path(store, LOCK)
    ok, msg = take_lock(lockp, session)
    if not ok:
        print(f"{tag}: skipped — {msg}")
        return 0
    try:
        ks, _how = load_keys(store)
        recover(store, ks)
        finish_migration(store, ks, now, session8)
        plans = do_pour(store, ks, spec, now, session8, via)
        n, line = pour_summary(plans)
        headline = (f"Archive — the hot tier poured whole, {n} entries into the keyspace" if archive
                    else f"Judged sweep placed mechanically — {n} pours into the keyspace")
        log_move(store, now, headline, [line], run_by)
        sync(store, ks, now)
        save_keys(store, ks)
        rewrite_index(store, now, session8, via, line, poured=[p["fname"] for p in plans])
        journal_compact(store)
    except Exception as e:  # noqa: BLE001
        release_lock(lockp, session)
        print(f"{tag}: stopped — {type(e).__name__}: {e}")
        return 1
    release_lock(lockp, session)
    print(f"{tag}: {line}; {check_verdict(store)}")
    return 0


def cmd_archive(store, session, now, dry=False):
    """/vlds:gc archive: every entry head of every hot object store, LIVE roots included and nothing exempt, placed
    through cmd_pour's own path — the hot tier emptied, the cold tier reached only by /vlds:recall. On the keyspace
    alone: a φ store has no runs to place into until it migrates."""
    if resolve(store)[0] != "idb":
        print("archive: refused — the store is on the φ-register; the archive places through the keyspace "
              "(migrate first)")
        return 1
    specs, counts = [], []
    for fname in sorted(OBJECT_STORES):
        heads = [b.line1 for b in (hot_blocks(store, fname) or [])]
        if heads:
            specs.append(f"{fname}:" + ",".join(str(h) for h in heads))
            counts.append(f"{len(heads)} {fname}")
    if not specs:
        print("archive: nothing to pour — every hot object store is empty")
        return 0
    if dry:
        print("archive: dry run — would pour " + ", ".join(counts) + "; nothing written")
        return 0
    return cmd_pour(store, session, now, specs, archive=True)


def cmd_compact(store, session, now, force=False):
    lockp = idb_path(store, LOCK)
    ok, msg = take_lock(lockp, session)
    if not ok:
        print(f"compact: skipped — {msg}")
        return 0
    try:
        ks, _how = load_keys(store)
        recover(store, ks)
        sync(store, ks, now)
        out = compact(store, ks, now, session[:8], force=force)
        if out:
            log_move(store, now, "Keyspace compaction", out, "Run mechanically by scripts/idb.py compact")
            sync(store, ks, now)
        save_keys(store, ks)
        journal_compact(store)
    except Exception as e:  # noqa: BLE001
        release_lock(lockp, session)
        print(f"compact: stopped — {type(e).__name__}: {e}")
        return 1
    release_lock(lockp, session)
    print("compact: " + ("; ".join(out) if out else "nothing owed") + f"; {check_verdict(store)}")
    return 0


# ─── migration ──────────────────────────────────────────────────────────────────────────────────────────

def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            with contextlib.suppress(OSError):
                total += os.path.getsize(os.path.join(root, f))
    return total


def migrate_refusal(store):
    """Why a φ store may not migrate now, or None: an open watermark (a pour the φ gc has not finished), a φ check that
    reports corruption (a torn pour, a voided watermark — rulings to reconcile first), a keyspace directory that is
    not empty, or too little disk for Chromium's margin."""
    for l in index_text(store).split("\n"):
        if l.startswith("|") and "mask=" in l:
            return f"an open watermark in the hot table ({l.strip()[:70]}) — the φ pour it marks is unfinished"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = phi.cmd_check(store, delegate=False)
    if rc != 0:
        first = next((l for l in buf.getvalue().split("\n") if l.startswith("[CORRUPT]")), "[CORRUPT] (unnamed)")
        return f"the φ check reports corruption — {first[len('[CORRUPT] '):]}"
    idb = os.path.join(store, IDB)
    if os.path.isdir(idb):
        extra = [f for f in os.listdir(idb) if f != LOCK]
        if extra:
            return f"idb/ exists without a keyspace ({', '.join(sorted(extra)[:4])}) — move it aside first"
    arc = os.path.join(store, "arc")
    size = dir_size(arc) if os.path.isdir(arc) else 0
    if size and shutil.disk_usage(store).free < MIGRATE_SPACE_FACTOR * size:
        return f"the disk holds less than {MIGRATE_SPACE_FACTOR}× the archive ({size:,} B)"
    return None


def build_from_phi(store, work, now, session8, budget_s=None):
    """Import arc/ into a keyspace under `work`: every segment entry verbatim into runs (its id kept, its key derived as
    a hot block's), every attachment and unregistered file byte for byte into blobs; then the hot tier synced on top.
    Returns (keyspace, counts); raises MigrateError on anything it cannot place."""
    arc = os.path.join(store, "arc")
    listing = sorted(os.listdir(arc)) if os.path.isdir(arc) else []
    segs = [f for f in listing if SEG_NAME_RE.match(f)]
    per_os, bodies = {}, {}
    t0 = time.monotonic()

    def in_time():
        if budget_s is not None and time.monotonic() - t0 >= budget_s:
            raise MigrateError(f"out of time after {budget_s:.0f} s — nothing committed; the next turn close tries again")
    for seg in segs:
        in_time()
        _header, entries, issues = phi.parse_segment(os.path.join(arc, seg))
        if issues:
            raise MigrateError(f"{seg}: {issues[0]}")
        for e in entries:
            first, _nl, rest = e.partition("\n")
            m = ID_RE.match(first)
            if not m:
                raise MigrateError(f"{seg}: an entry without an id line")
            rid = f"{m.group(1)}-{m.group(2)}"
            body = rest.lstrip("\n")
            if rid in bodies:
                if bodies[rid] == body:
                    continue
                raise MigrateError(f"{rid} holds two different bodies (the second in {seg})")
            bodies[rid] = body
            per_os.setdefault(PREFIX_OS.get(m.group(1), "legacy"), []).append((first, rid, body))
    os.makedirs(os.path.join(work, RUNS), exist_ok=True)
    ks = Keyspace.fresh()
    next_run = 1
    with idb_root(store, work):
        for os_ in sorted(per_os):
            in_time()
            items, seen = [], {}
            for first, rid, body in per_os[os_]:
                field, value, fields = parse_block(body)
                base = base_pk(body.split("\n", 1)[0], field, value, fields)
                seen[base] = seen.get(base, 0) + 1
                pk = base if seen[base] == 1 else f"{base}#{seen[base]}"
                items.append((pk, first, rid, body, field, value, fields))
                gen = int(rid.split("-", 1)[1])
                ks.meta[(os_, "key-generator")] = str(max(int(ks.meta.get((os_, "key-generator"), "0")), gen))
            items.sort(key=lambda it: it[0])
            groups, cur, size = [], [], 0
            for it in items:
                n = len(it[3].encode("utf-8")) + 64
                if cur and size + n > RUN_TARGET:
                    groups.append(cur)
                    cur, size = [], 0
                cur.append(it)
                size += n
            if cur:
                groups.append(cur)
            v = 0
            for g in groups:
                name = f"{os_}-{next_run:06d}.md"
                next_run += 1
                ents = []
                for pk, first, rid, body, *_rest in g:
                    wrap = len(body.encode("utf-8")) > WRAP_BYTES or any(
                        l.startswith("```") or l == "---" for l in body.split("\n"))
                    if wrap:
                        rel = f"{BLOBS}/{os_}/{rid}.md"
                        os.makedirs(os.path.dirname(rel_path(store, rel)), exist_ok=True)
                        write_text(rel_path(store, rel), body)
                        ks.blobs[(os_, f"{rid}.md")] = blob_fields(rel_path(store, rel), rel, os_, "arc")
                        body = f"(wrapped: {rel} sha={sha(bodies[rid])})"
                    ents.append((first, pk, body))
                text, line1s = render_run(name, os_, ents, now, session8, "the migration from arc/ (scripts/idb.py migrate)")
                write_text(rel_path(store, f"{RUNS}/{name}"), text)
                for (pk, first, rid, body, field, value, fields), l1 in zip(g, line1s):
                    v += 1
                    ks.records[(os_, pk)] = {"v": str(v), "sha": sha(body), "at": f"runs/{name}:{l1}", "id": rid,
                                             "state": "freed" if "(tombstoned)" in first else "live"}
                    for typ, ikey in index_keys(os_, field, value, fields, rid):
                        ks.index[(os_, typ, f"{ikey}|{pk}")] = {"v": str(v)}
            ks.meta[(os_, "last-version")] = str(v)
        n_blobs = 0
        for name in listing:
            src = os.path.join(arc, name)
            if name in segs or name == LOCK or not os.path.isfile(src):
                continue
            in_time()
            sub = "dispatch" if POURED_DISPATCH_RE.match(name) else "legacy"
            dst = rel_path(store, f"{BLOBS}/{sub}/{name}")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            if file_sha(dst) != file_sha(src):
                raise MigrateError(f"arc/{name}: the copy did not read back byte-identical")
            ks.blobs[(sub, name)] = blob_fields(dst, f"{BLOBS}/{sub}/{name}", sub, "arc")
            n_blobs += 1
        ks.meta[("@", "next-run")] = str(next_run)
        ks.meta[("@", "migrated-runs")] = str(next_run)
        ks.meta[("@", "migrated")] = (f"{now} by {session8} from arc/ — {len(segs)} segments, {len(bodies)} entries, "
                                      f"{n_blobs} blobs")
        sync(store, ks, now)
        # verify: every segment entry, found by its id, body for body (a wrapped one in its blob); every blob byte-equal
        found = {}
        for name in os.listdir(os.path.join(work, RUNS)):
            for e in parse_run(os.path.join(work, RUNS, name))[1]:
                found[e.rid] = unwrap(store, e.body)
        for rid, body in bodies.items():
            if found.get(rid) != body:
                raise MigrateError(f"{rid}: not verbatim in the runs")
        for (sub, name), f in ks.blobs.items():
            if f.get("from") == "arc" and sub in ("dispatch", "legacy") and \
                    file_sha(os.path.join(arc, name)) != file_sha(rel_path(store, f["blob"])):
                raise MigrateError(f"arc/{name}: its blob differs")
        save_keys(store, ks)
        _ks2, errors = Keyspace.load(idb_path(store, KEYS))
        if errors:
            raise MigrateError(f"the keyspace written does not read back: {errors[0]}")
    return ks, {"segments": len(segs), "entries": len(bodies), "blobs": n_blobs, "runs": next_run - 1}


def cmd_migrate(store, session, now, dry=False, shadow=False, budget_s=None):
    """The gentle migration: preconditions, the import into idb.tmp/ (or a temporary directory for --dry/--shadow),
    verification, then the commit — idb.tmp/ renamed to idb/ — and the steps after it."""
    session8 = session[:8]
    tag = "shadow" if shadow else "migrate"
    if store_state(store) == "idb":
        print(f"{tag}: the store is on the keyspace already")
        return 0
    reason = migrate_refusal(store)
    if reason:
        print(f"{tag}: {'migration would be refused' if shadow else 'refused'} — {reason}")
        return 0 if shadow else 1
    trial = dry or shadow
    parent = tempfile.mkdtemp(prefix="vlds-idb-") if trial else None
    work = os.path.join(parent, IDB) if trial else os.path.join(store, IDB + ".tmp")
    arc_lock = os.path.join(store, "arc", LOCK)
    locked = False
    try:
        if os.path.exists(work):
            shutil.rmtree(work)
        if not trial and os.path.isdir(os.path.join(store, "arc")):
            ok, msg = take_lock(arc_lock, session)
            if not ok:
                print(f"{tag}: skipped — the φ {msg}")
                return 0
            locked = True
        try:
            _ks, counts = build_from_phi(store, work, now, session8, budget_s)
        except Exception as e:  # noqa: BLE001 — any failure is a refusal the report names; nothing was committed
            why = str(e) if isinstance(e, MigrateError) else f"{type(e).__name__}: {e}"
            print(f"{tag}: {'migration would fail' if shadow else 'refused'} — {why}")
            return 0 if shadow else 1
        what = (f"{counts['segments']} segments, {counts['entries']} entries → {counts['runs']} runs, "
                f"{counts['blobs']} blobs, every entry verbatim and every blob byte-identical")
        if trial:
            print(f"{tag}: migration would pass — {what}" + ("" if shadow else "; dry run, nothing written"))
            return 0
        idb = os.path.join(store, IDB)
        if os.path.isdir(idb):
            shutil.rmtree(idb)          # migrate_refusal allowed only a stale lock in it
        os.replace(work, idb)           # the commit point: from here the store is on the keyspace, whatever follows
        try:
            ks, _how = load_keys(store)
            notes = finish_migration(store, ks, now, session8)
            save_keys(store, ks)
            locked = False              # the φ lock left with arc/; finish_migration removed it
        except Exception as e:  # noqa: BLE001 — the steps after the commit are idempotent; the next pass finishes them
            print(f"{tag}: migrated to the keyspace — {what}; the steps after the commit stopped "
                  f"({type(e).__name__}: {e}) and the next pass finishes them")
            return 0
        log_move(store, now, f"Migrated to the keyspace — {counts['entries']} entries",
                 [what] + notes, "Run mechanically by scripts/idb.py migrate; rollback: scripts/idb.py rollback")
        print(f"{tag}: migrated to the keyspace — {what}; " + "; ".join(notes) + f"; {check_verdict(store)}")
        return 0
    finally:
        if locked:
            release_lock(arc_lock, session)
        if parent:
            shutil.rmtree(parent, ignore_errors=True)
        elif os.path.isdir(work):
            shutil.rmtree(work, ignore_errors=True)


def set_recall_key(text, key, value):
    """The index text with `key: value` under ## recall — replaced where it stands, else added at the section's end, the
    section added when there is none."""
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "## recall"), None)
    if start is None:
        return text.rstrip("\n") + f"\n\n## recall\n\n{key}: {value}\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    for i in range(start + 1, end):
        if re.match(rf"^{re.escape(key)}:", lines[i].strip()):
            lines[i] = f"{key}: {value}"
            return "\n".join(lines)
    last = max((i for i in range(start + 1, end) if lines[i].strip() and not lines[i].startswith("updated:")),
               default=start)
    lines.insert(last + 1, f"{key}: {value}")
    return "\n".join(lines)


def splice_section(old, new, name):
    """`old` with its `## name` section's body replaced by `new`'s, verbatim; `old` unchanged when `new` has none."""
    def span(lines):
        s = next((i for i, l in enumerate(lines) if l.strip().lower() == f"## {name}"), None)
        if s is None:
            return None, None
        e = next((i for i in range(s + 1, len(lines)) if lines[i].startswith("## ") or lines[i].startswith("updated:")),
                 len(lines))
        return s, e
    ol, nl = old.split("\n"), new.split("\n")
    ns, ne = span(nl)
    if ns is None:
        return old
    os_, oe = span(ol)
    body = nl[ns:ne]
    while body and not body[-1].strip():
        body.pop()
    if os_ is None:
        return old.rstrip("\n") + "\n\n" + "\n".join(body) + "\n"
    return "\n".join(ol[:os_] + body + [""] + ol[oe:])


def retired_entries(retired):
    """{id: body} for every entry of the retired arc's segments — what a rollback returns without touching."""
    out = {}
    for name in sorted(os.listdir(retired)) if os.path.isdir(retired) else []:
        if SEG_NAME_RE.match(name):
            _h, entries, _issues = phi.parse_segment(os.path.join(retired, name))
            for e in entries:
                first, _nl, rest = e.partition("\n")
                m = ID_RE.match(first)
                if m:
                    out[f"{m.group(1)}-{m.group(2)}"] = rest.lstrip("\n")
    return out


def cmd_rollback(store, session, now, dry=False):
    """Return a migrated store to the φ-register, at any point: every entry poured since the migration goes back to its
    hot file verbatim (where the φ sweep can pour it again), arc/ comes back from its retired name, the φ index comes
    back with the current ## recall section and budgets and `index-engine: phi` (so the next turn close does not migrate
    again), every dispatch record poured since — registered or not — moves into arc/ for the φ sweep to attach, history
    the runs hold is kept in arc/, and idb/ is removed. Planned under the lock; refused when an archived entry was edited
    in the keyspace since (the returning arc would lose the edit) or a dispatch pour is in flight. Resumable: a crash
    part-way is finished by running it again, and the keyspace's own passes wait until it is."""
    tag = "rollback"
    if store_state(store) != "idb":
        print(f"{tag}: refused — the store is not on the keyspace")
        return 1
    if dry:
        return rollback_plan(store, now, tag, dry=True)
    lockp = idb_path(store, LOCK)
    ok, msg = take_lock(lockp, session)
    if not ok:
        print(f"{tag}: skipped — {msg}")
        return 0
    try:
        return rollback_plan(store, now, tag, dry=False)
    finally:
        release_lock(lockp, session)


def rollback_plan(store, now, tag, dry):
    ks, _how = load_keys(store)
    if not ks.meta.get(("@", "migrated")):
        print(f"{tag}: refused — the keyspace was not migrated from a φ-register; there is no arc/ to return to")
        return 1
    resuming = os.path.exists(idb_path(store, ROLLBACK_MARK))
    retired = os.path.join(store, ks.meta.get(("@", "retired"), RETIRED))
    arc = os.path.join(store, "arc")
    source = arc if resuming and os.path.isdir(arc) and not os.path.isdir(retired) else retired
    if not os.path.isdir(source) or not os.path.exists(os.path.join(source, INDEX_FILE)):
        print(f"{tag}: refused — {os.path.basename(retired)}/ or its saved φ index is missing")
        return 1
    if os.path.exists(arc) and source != arc:
        print(f"{tag}: refused — arc/ exists; move it aside first")
        return 1
    _settled, young = settle_pending(store, ks)
    if young:
        print(f"{tag}: refused for now — a dispatch pour is in flight ({young[0]}); run it again in a minute")
        return 1
    archived = retired_entries(source)
    cache, poured, edited = RunCache(store), {}, []
    for (os_, pk), r in sorted(ks.cold().items()):
        e = cache.entry(r["at"])
        body = unwrap(store, e.body) if e is not None else None
        if body is None:
            print(f"{tag}: refused — {os_} {pk} names {r['at']}, which holds no entry; `idb.py check` first")
            return 1
        if r.get("id") in archived:
            if archived[r["id"]] != body:
                edited.append(r["id"])
        else:
            poured.setdefault(os_, []).append(body)
    if edited:
        print(f"{tag}: refused — {len(edited)} archived entr{'y was' if len(edited) == 1 else 'ies were'} edited in the "
              f"keyspace since the migration ({', '.join(edited[:5])}); the returning arc would lose the edit")
        return 1
    absent = [os_ for os_ in poured if not os.path.exists(os.path.join(store, os_ + ".md"))]
    if absent and not resuming:
        print(f"{tag}: refused — the hot file {absent[0]}.md is gone, and {len(poured[absent[0]])} entr(ies) poured "
              "since the migration would have nowhere to return")
        return 1
    source_names = set(os.listdir(source))
    moving = []                 # every record on disk the returning arc lacks, registered or not
    for sub in ("dispatch", "legacy"):
        d = idb_path(store, BLOBS, sub)
        for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if name not in source_names:
                moving.append((sub, name))
    named = {(r["at"][len("runs/"):].rpartition(":")[0], int(r["at"].rpartition(":")[2])) for r in ks.cold().values()}
    history = []
    runs_dir = idb_path(store, RUNS)
    for name in sorted(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else []:
        if not RUN_NAME_RE.match(name):
            continue
        for e in parse_run(os.path.join(runs_dir, name))[1]:
            body = unwrap(store, e.body)
            if (name, e.line1) not in named and archived.get(e.rid) != body:
                history.append((e.id_line, e.pk, body))
    n_back = sum(len(v) for v in poured.values())
    if dry:
        print(f"{tag}: dry run — {n_back} entr(ies) poured since the migration back to their hot files, "
              f"{os.path.basename(retired)}/ → arc/, the φ index restored, {len(moving)} record(s) moved into arc/, "
              f"{len(history)} history entr(ies) kept, idb/ removed; nothing written")
        return 0
    if not resuming:            # the returns, once: the mark says they are made, so a crash is resumed, never redone
        for os_, bodies in poured.items():
            path = os.path.join(store, os_ + ".md")
            raw = read_raw(path)
            text = raw.replace("\r\n", "\n").rstrip("\n") + "\n" + "".join(f"\n{b}\n" for b in bodies)
            write_text(path, text, crlf="\r\n" in raw)
        write_text(idb_path(store, ROLLBACK_MARK), f"{now}\n" + "".join(f"{k} {len(v)}\n" for k, v in poured.items()))
    old_raw = read_raw(os.path.join(source, INDEX_FILE))
    restored = splice_section(old_raw.replace("\r\n", "\n"), index_text(store), "recall")
    restored = set_recall_key(restored, "index-engine", "phi")
    cur_budget = {row[0]: row[4] for row in (phi.parse_index(store) or {}).get("hot", []) if len(row) > 4}
    out = []
    for l in restored.split("\n"):
        cells = [c.strip() for c in l.strip("|").split("|")]
        if l.startswith("|") and len(cells) > 4 and cells[0] in cur_budget:
            cells[4] = cur_budget[cells[0]]
            l = "| " + " | ".join(cells) + " |"
        out.append(l)
    if source != arc:
        os.replace(source, arc)
    kept = ""
    if history:
        kept = f"keyspace-history-{clock(now):%Y%m%d-%H%M}.md"
        write_text(os.path.join(arc, kept), "# Keyspace history\n\nText the keyspace held as history — an older "
                   "version an edit superseded, a key held twice — kept verbatim at its rollback; the φ gc judges its "
                   "registration or collection.\n\n"
                   + "".join(f"---\n{i}\nkey: {k}\n\n{b}\n" for i, k, b in history))
    for sub, name in moving:
        shutil.move(idb_path(store, BLOBS, sub, name), os.path.join(arc, name))
    write_text(os.path.join(store, INDEX_FILE), "\n".join(out), crlf="\r\n" in old_raw)
    with contextlib.suppress(OSError):
        os.remove(os.path.join(arc, INDEX_FILE))
    shutil.rmtree(os.path.join(store, IDB))
    back = ", ".join(f"{len(v)} to {k}.md" for k, v in sorted(poured.items())) or "none"
    log_move(store, now, "Keyspace rolled back to the φ-register",
             [f"{n_back} entr(ies) poured since the migration returned to their hot files ({back})"
              + (" — returned before a crash; the rollback resumed" if resuming else ""),
              f"{os.path.basename(retired)}/ returned to arc/", "the φ index restored with the current ## recall "
              "section and budgets, index-engine: phi", f"{len(moving)} record(s) poured since moved into arc/"]
             + ([f"{len(history)} history entr(ies) kept in arc/{kept}"] if history else []),
             "Run by scripts/idb.py rollback on the owner's word")
    print(f"{tag}: the store is on the φ-register again — {n_back} entr(ies) poured since the migration back in their "
          f"hot files ({back}), arc/ restored, index-engine: phi set, {len(moving)} record(s) moved into arc/ for the "
          "light sweep to attach" + (f", {len(history)} history entr(ies) kept in arc/{kept}" if history else "")
          + "; idb/ removed")
    return 0


# ─── reads ──────────────────────────────────────────────────────────────────────────────────────────────

def find_record(ks, os_, key):
    if (os_, key) in ks.records:
        return key, ks.records[(os_, key)]
    for (o, pk), r in ks.records.items():
        if o == os_ and r.get("id") == key:
            return pk, r
    return None, None


def record_text(store, os_, pk, r, cache=None):
    """(text, note) for a record, validated: a hot hint checked by sha, the hot file rescanned when the hint moved; a
    cold entry checked for its key and sha. The note names what the reader must know — behind a hand edit, moved."""
    at = r.get("at", "")
    if at.startswith("hot:"):
        blocks = hot_blocks(store, os_ + ".md") or []
        b = next((b for b in blocks if b.line1 == int(at[4:])), None)
        if b is not None and sha(b.text) == r.get("sha"):
            return b.text, ""
        same = [b for b in blocks if sha(b.text) == r.get("sha")]
        if same:
            return same[0].text, f"the hint moved: now at hot line {same[0].line1}"
        base = SUFFIX_RE.sub("", pk)
        edited = [b for b in blocks if block_pk(b) == base]
        if edited:
            return edited[0].text, "BEHIND — the entry was edited since the last sync; the hot file's text, which rules"
        return "", "GONE — the entry left the hot file since the last sync"
    cache = cache or RunCache(store)
    e = cache.entry(at)
    if e is None or e.pk != pk:
        return "", f"MISSING — {at} holds no entry keyed {pk}"
    body = unwrap(store, e.body)
    note = "" if sha(body) == r.get("sha") else "the run's text differs from the keyspace's sha — a hand edit, a ruling"
    return body, note


def record_line(os_, pk, r):
    extra = "".join(f" {k}={r[k]}" for k in ("id", "state", "ts") if k in r)
    return f"{os_} {pk} v={r.get('v')} at={r.get('at')}{extra}"


def cmd_get(store, os_, key):
    ks, _how = load_keys(store)
    pk, r = find_record(ks, os_, key)
    if r is None:
        print(f"get: {os_} holds no record keyed or numbered {key!r}")
        return 1
    text, note = record_text(store, os_, pk, r)
    print(record_line(os_, pk, r))
    if r.get("state") == "freed":
        print(f"FREED by {r.get('ts')} — surfaced, never applied")
    if note:
        print(f"note: {note}")
    print(text)
    return 0


def cmd_range(store, os_, lo, hi=None):
    ks, _how = load_keys(store)
    cache, n = RunCache(store), 0
    for (o, pk), r in sorted(ks.records.items()):
        if o != os_ or pk < lo or (hi is not None and pk >= hi) or (hi is None and not pk.startswith(lo)):
            continue
        text, note = record_text(store, o, pk, r, cache)
        print(record_line(o, pk, r) + " — " + phi.clip(" ".join(text.split("\n", 1)[0].split()), 110)
              + (f" ({note})" if note else ""))
        n += 1
    print(f"range: {n} record(s)")
    return 0


def cmd_find(store, os_, index, key):
    ks, _how = load_keys(store)
    cache, n, stale = RunCache(store), 0, 0
    for (o, typ, ikey), f in sorted(ks.index.items()):
        if o != os_ or not (typ == index or typ.split(":", 1)[-1] == index):
            continue
        ik, _sep, pk = ikey.partition("|")
        if ik != key:
            continue
        r = ks.records.get((o, pk))
        if r is None or r.get("v") != f.get("v"):
            stale += 1
            continue
        text, note = record_text(store, o, pk, r, cache)
        print(record_line(o, pk, r) + " — " + phi.clip(" ".join(text.split("\n", 1)[0].split()), 110)
              + (f" ({note})" if note else ""))
        n += 1
    print(f"find: {n} record(s)" + (f"; {stale} stale index line(s) skipped" if stale else ""))
    return 0


def cmd_blobs(store, kind=None):
    """Every registered external object, or those under one blobs/ subdirectory (dispatch, legacy, an object store's
    wrapped entries): its name, size, rows and recorded sha — what `blob` can read."""
    ks, _how = load_keys(store)
    n = 0
    for (k, name), f in sorted(ks.blobs.items()):
        if kind and k != kind:
            continue
        print(f"{k} {name} bytes={f.get('bytes')} rows={f.get('rows')} sha={f.get('sha')}")
        n += 1
    print(f"blobs: {n} external object(s)" + (f" under {kind}" if kind else ""))
    return 0


def cmd_blob(store, kind, name):
    """One external object's text, read only when the keyspace registers it and the file still hashes to the sha it
    recorded: an unregistered blob (a pour the next sync has not registered yet) or a changed one is refused, and the
    check is where either is settled."""
    ks, _how = load_keys(store)
    f = ks.blobs.get((kind, name))
    if f is None:
        print(f"blob: {kind}/{name} is not a registered external object — `blobs {kind}` lists the registered ones")
        return 1
    rel = f.get("blob") or f"{BLOBS}/{kind}/{name}"
    path = rel_path(store, rel)
    if not os.path.exists(path):
        print(f"blob: {rel} is registered but missing on disk — the check reports it")
        return 1
    if file_sha(path) != f.get("sha"):
        print(f"blob: {rel} no longer hashes to the sha the keyspace recorded ({f.get('sha')}) — refused; a hand edit "
              "or a torn write is the check's to settle")
        return 1
    print(f"{kind} {name} bytes={f.get('bytes')} rows={f.get('rows')} sha={f.get('sha')}")
    print(read_text(path))
    return 0


# ─── check ──────────────────────────────────────────────────────────────────────────────────────────────

def cmd_check(store):
    """The keyspace's structural scans, report-only, plus the store-level scans phi.py check keeps (run in-process:
    with arc/ gone and the index in the keyspace's shape its φ scans find nothing, so what it prints is exactly the
    kept set). Exit 1 = corruption."""
    if store_state(store) != "idb":
        print("idb.py check: the store is not on the keyspace — phi.py check follows")
        return phi.cmd_check(store, delegate=False)
    corrupt, debt, stray, notes = [], [], [], []
    p = idb_path(store, KEYS)
    ks = None
    if not os.path.exists(p):
        corrupt.append("idb/keys.tsv absent — the keyspace is gone; `idb.py sync --full` rebuilds it from the files")
    else:
        ks, errors = Keyspace.load(p)
        for e in errors[:10]:
            corrupt.append(f"keys.tsv {e} — `idb.py sync --full` rebuilds it")
        if ks.meta.get(("@", "schema")) != SCHEMA:
            corrupt.append(f"keys.tsv schema {ks.meta.get(('@', 'schema'))!r}, not {SCHEMA}")
    if ks is not None:
        # 2. versions: every object store's counter at least every record's version
        for os_ in sorted({o for o, _pk in ks.records}):
            last = int(ks.meta.get((os_, "last-version"), "0") or 0)
            top = max(int(r.get("v", 0) or 0) for (o, _pk), r in ks.records.items() if o == os_)
            if top > last:
                corrupt.append(f"{os_}: a record at version {top} past last-version {last}")
        # 3. the cold tier: the run exists, the line holds the key, the text hashes to the record's sha
        cache = RunCache(store)
        for (os_, pk), r in sorted(ks.cold().items()):
            name = r["at"][len("runs/"):].rpartition(":")[0]
            if not os.path.exists(rel_path(store, f"{RUNS}/{name}")):
                corrupt.append(f"{os_} {pk} names a missing run {name}")
                continue
            text, note = record_text(store, os_, pk, r, cache)
            if note.startswith("MISSING"):
                corrupt.append(f"{os_} {pk}: {note}")
            elif note:
                notes.append(f"{os_} {pk} ({r.get('id', '')}): {note}; `idb.py sync --full` re-reads it")
        # the hot tier against the keyspace: what a sync would change
        edited = unsynced = 0
        for fname in sorted(OBJECT_STORES):
            os_ = fname[:-3]
            blocks = hot_blocks(store, fname) or []
            cold = {pk for (o, pk) in ks.cold(os_)}
            for pk, b in zip(assign_pks(blocks, cold), blocks):
                r = ks.records.get((os_, pk))
                if r is None:
                    unsynced += 1
                elif r.get("sha") != sha(b.text):
                    edited += 1
        if unsynced or edited:
            notes.append(f"the hot tier moved since the last sync: {unsynced} entr{'y' if unsynced == 1 else 'ies'} "
                         f"not indexed yet, {edited} edited — the next turn close syncs them")
        # 4. index lines: live only while the record exists at the same version
        stale = 0
        for (o, _t, ikey), f in ks.index.items():
            r = ks.records.get((o, ikey.split("|", 1)[-1]))
            if r is None or r.get("v") != f.get("v"):
                stale += 1
        if stale:
            debt.append(f"{stale} stale index line(s) — the next sync sweeps them")
        # 5. external objects: present; bytes and sha as registered
        for (sub, name), f in sorted(ks.blobs.items()):
            bp = rel_path(store, f.get("blob", ""))
            if not os.path.exists(bp):
                corrupt.append(f"blob {sub}/{name} missing from idb/{f.get('blob')}")
            elif f.get("sha") != file_sha(bp) or f.get("bytes") != str(os.path.getsize(bp)):
                notes.append(f"blob {sub}/{name} changed since it was registered — a hand edit is a ruling; "
                             "`idb.py sync --full` re-registers it")
        # 6. the journal: an intent still open is a torn commit; a dispatch pour marked in flight too long, the same
        for (op, jid), jl in journal_open(journal_read(store)).items():
            debt.append(f"journal: {op} {jid} still {jl.state} — the next pass recovers it")
        for name, age in sorted(pending_markers(store).items()):
            if age >= BLOB_PENDING_GRACE_S:
                debt.append(f"idb/pending/{name}: a dispatch pour that never closed — the next pass settles it")
        # 7. files the keyspace does not name
        named = {r["at"][len("runs/"):].rpartition(":")[0] for r in ks.cold().values()}
        claimed = {jl.jid for jl in journal_read(store)} | {f"{BLOBS}/dispatch/{n}" for n in pending_markers(store)}
        runs_dir = idb_path(store, RUNS)
        for name in sorted(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else []:
            if RUN_NAME_RE.match(name):
                try:
                    parse_run(os.path.join(runs_dir, name))
                except (ValueError, OSError) as e:
                    corrupt.append(f"runs/{name} does not parse ({e}) — a hand edit broke its grammar")
                    continue
            if name.endswith(".tmp"):
                debt.append(f"runs/{name}: a temporary file a crash left — the gc collects it")
            elif name not in named and name not in claimed:
                notes.append(f"runs/{name}: no live record names it — history only (kept; never collected by script)")
        bdir = idb_path(store, BLOBS)
        for sub in sorted(os.listdir(bdir)) if os.path.isdir(bdir) else []:
            for name in sorted(os.listdir(os.path.join(bdir, sub))) if os.path.isdir(os.path.join(bdir, sub)) else []:
                if (sub, name) not in ks.blobs and f"{BLOBS}/{sub}/{name}" not in claimed:
                    debt.append(f"blobs/{sub}/{name}: unregistered — the next sync registers it")
        # 8. uniqueness: one id, one record
        ids = {}
        for (os_, pk), r in ks.records.items():
            if r.get("id"):
                ids.setdefault(r["id"], []).append(f"{os_} {pk}")
        for rid, where in sorted(ids.items()):
            if len(where) > 1:
                corrupt.append(f"id {rid} held by {len(where)} records ({'; '.join(where)}) — one fact, one place")
        # a migration's leftovers
        if ks.meta.get(("@", "migrated")):
            if os.path.isdir(os.path.join(store, "arc")):
                debt.append("arc/ still present after the migration — the next pass moves it aside")
            if re.search(r"^register:", index_text(store), re.M):
                debt.append("phi-index.md still carries the φ register — the next pass rewrites it")
    # the store-level scans phi.py check keeps
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        phi.cmd_check(store, delegate=False)
    for l in buf.getvalue().split("\n"):
        for tag, bucket in (("[CORRUPT] ", corrupt), ("[DEBT] ", debt), ("[STRAY] ", stray), ("[note] ", notes)):
            if l.startswith(tag):
                bucket.append(l[len(tag):])
    for tag, items in (("CORRUPT", corrupt), ("DEBT", debt), ("STRAY", stray), ("note", notes)):
        for i in items:
            print(f"[{tag}] {i}")
    print(f"idb.py check: {len(corrupt)} corruption, {len(debt)} debt, {len(stray)} stray, {len(notes)} notes")
    return 1 if corrupt else 0


# ─── the pool's snapshot ────────────────────────────────────────────────────────────────────────────────

def hot_snapshot(store, ks=None):
    """{(object store, primary key): sha} for the hot tier as it stands — derived, nothing written."""
    if ks is None:
        p = idb_path(store, KEYS)
        ks = Keyspace.load(p)[0] if os.path.exists(p) else Keyspace.fresh()
    out = {}
    for fname in sorted(OBJECT_STORES):
        os_ = fname[:-3]
        blocks = hot_blocks(store, fname) or []
        cold = {pk for (o, pk) in ks.cold(os_)}
        for pk, b in zip(assign_pks(blocks, cold), blocks):
            out[(os_, pk)] = sha(b.text)
    return out


def pool_owner(store):
    p = os.path.join(store, POOL_FILE)
    if not os.path.exists(p):
        return None
    m = re.search(r"^session:\s*([0-9A-Za-z-]+)", read_text(p), re.M)
    return m.group(1)[:8] if m else None


def cmd_pool_stamp(store, now, quiet=False):
    """Snapshot the hot tier beside the pool just written: `idb/pool-stamp.tsv`, the pool's sha on its first line.
    Run by the post-write hook whenever recall-pool.md changed; writes nothing else."""
    pool = os.path.join(store, POOL_FILE)
    if not os.path.exists(pool):
        if not quiet:
            print("pool-stamp: no recall-pool.md")
        return 0
    os.makedirs(idb_path(store), exist_ok=True)
    snap = hot_snapshot(store)
    body = "".join(f"{o}\t{pk}\t{h}\n" for (o, pk), h in sorted(snap.items()))
    write_text(idb_path(store, POOL_STAMP), f"# pool {pool_owner(store) or '-'} {file_sha(pool)} {now}\n" + body)
    if not quiet:
        print(f"pool-stamp: {len(snap)} hot entries stamped beside the pool of {pool_owner(store) or '-'}")
    return 0


def pool_stamp_current(store):
    """True when the stamp names the pool file as it stands."""
    p, pool = idb_path(store, POOL_STAMP), os.path.join(store, POOL_FILE)
    if not os.path.exists(p) or not os.path.exists(pool):
        return False
    head = read_text(p).split("\n", 1)[0].split()
    return len(head) >= 4 and head[3] == file_sha(pool)


def pool_diff(store):
    """One line: the pool is current, or what the hot tier gained, changed or lost since it was pooled."""
    p, pool = idb_path(store, POOL_STAMP), os.path.join(store, POOL_FILE)
    if not os.path.exists(pool):
        return "pool: none written"
    if not pool_stamp_current(store):
        return "pool: no stamp for this pool file — its freshness cannot be told; re-read before an entry steers"
    lines = read_text(p).split("\n")
    head = lines[0].split()
    when = " ".join(head[4:6]) if len(head) >= 6 else "?"
    then = {}
    for l in lines[1:]:
        parts = l.split("\t")
        if len(parts) == 3:
            then[(parts[0], parts[1])] = parts[2]
    now_ = hot_snapshot(store)
    per = {}
    for k, h in now_.items():
        if k not in then:
            per.setdefault(k[0], [0, 0, 0])[0] += 1
        elif then[k] != h:
            per.setdefault(k[0], [0, 0, 0])[1] += 1
    for k in then:
        if k not in now_:
            per.setdefault(k[0], [0, 0, 0])[2] += 1
    if not per:
        return f"pool: current — no hot entry written since it was pooled at {when}"
    total = sum(sum(v) for v in per.values())
    parts = []
    for os_, (new, changed, gone) in sorted(per.items()):
        bits = [f"{new} new" if new else "", f"{changed} changed" if changed else "", f"{gone} removed" if gone else ""]
        parts.append(f"{os_}.md {' '.join(b for b in bits if b)}")
    return (f"pool: predates {total} write{'s' if total != 1 else ''} since it was pooled at {when} — "
            + "; ".join(parts) + " — the entries there are re-read before they steer")


# ─── digest ─────────────────────────────────────────────────────────────────────────────────────────────

def keyspace_digest(store):
    """The SessionStart lines for a store on the keyspace: the engine, the keyspace in one line, the migration."""
    engine, setting, state = resolve(store)
    _s, named = engine_setting(store)
    out = [f"engine: idb (index-engine: {setting}{'' if named else ', the default'}"
           + (" — a store with a keyspace stays on it; `idb.py rollback` is the way back)" if setting == "phi" else ")")]
    p = idb_path(store, KEYS)
    if not os.path.exists(p):
        out.append("keyspace: none yet — the first turn close starts it (scripts/idb.py light)")
        return "\n".join(out)
    ks, errors = Keyspace.load(p)
    hot = sum(1 for r in ks.records.values() if r.get("at", "").startswith("hot:"))
    cold = len(ks.records) - hot
    freed = sum(1 for r in ks.records.values() if r.get("state") == "freed")
    runs_dir = idb_path(store, RUNS)
    runs = len([n for n in os.listdir(runs_dir) if RUN_NAME_RE.match(n)]) if os.path.isdir(runs_dir) else 0
    stores = len({o for o, _pk in ks.records})
    out.append(f"keyspace: {len(ks.records)} records — {hot} hot, {cold} cold ({freed} freed) in {stores} object "
               f"stores; {runs} runs, {len(ks.blobs)} blobs; synced {ks.meta.get(('@', 'synced'), '-')}"
               + (f"; {len(errors)} unreadable line(s)" if errors else ""))
    if ks.meta.get(("@", "migrated")):
        out.append(f"migrated: {ks.meta[('@', 'migrated')]}; retired arc kept at {ks.meta.get(('@', 'retired'), RETIRED)}/")
    return "\n".join(out)


def phi_engine_line(store):
    """For a φ store: one line on what its stage does here — '' only when the index names no stage and the default
    leaves the store on the φ-register, so a migration the default owes is announced before it runs."""
    engine, setting, state = resolve(store)
    _s, named = engine_setting(store)
    if engine == "idb" or (not named and engine == "phi"):
        return ""
    what = {"shadow": "the φ-register runs; each turn close adds a shadow migration's verdict",
            "phi": "the φ-register runs" + (" — a φ store stays φ at this stage" if setting == "idb-new-stores" else ""),
            "migrate": "migrates to the keyspace at the next turn close once the φ check is clean"}[engine]
    return f"engine: phi (index-engine: {setting}{'' if named else ', the default'}) — {what}"


# ─── main ───────────────────────────────────────────────────────────────────────────────────────────────

def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="idb.py", description="VLDS keyspace — IndexedDB's indexing in plain text")
    ap.add_argument("--store", default=os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", "p4", "vlds"))
    sub = ap.add_subparsers(dest="cmd")

    def writer(name, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("--session", required=True, help="the session id — the lock holder and the updated: line")
        p.add_argument("--now", default=None, help="the clock, YYYY-MM-DD HH:MM, copied from the hook stream")
        return p
    p = writer("sync")
    p.add_argument("--full", action="store_true", help="rebuild the keyspace from the files alone")
    p.add_argument("--budget-s", type=float, default=SYNC_BUDGET_S, help="the round's wall-clock budget")
    p = writer("light")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--budget-s", type=float, default=None, help="leave the pour, the compaction and the check to the next "
                                                                "pass once this many seconds are spent")
    p = writer("pour")
    p.add_argument("specs", nargs="+", metavar="FILE:L1,L2", help="a hot file and the head lines of its cold entries")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--archive", action="store_true", help="let a LIVE ruling or rule pour — /vlds:gc archive's flag")
    p = writer("archive")
    p.add_argument("--dry", action="store_true", help="print the counts per object store; write nothing")
    p = writer("compact")
    p.add_argument("--force", action="store_true", help="compact every object store with two or more small runs now")
    p = writer("migrate")
    p.add_argument("--dry", action="store_true", help="import and verify in a temporary directory; write nothing")
    p.add_argument("--shadow", action="store_true", help="idb-control's verdict: --dry in one line")
    p.add_argument("--budget-s", type=float, default=None, help="stop cleanly, committing nothing, past this many seconds")
    p = writer("rollback")
    p.add_argument("--dry", action="store_true")
    p = writer("pool-stamp")
    p = sub.add_parser("get")
    p.add_argument("object_store")
    p.add_argument("key", help="a primary key, or an id such as lg-0012")
    p = sub.add_parser("range")
    p.add_argument("object_store")
    p.add_argument("lo", help="the lower key, inclusive (alone: a prefix)")
    p.add_argument("hi", nargs="?", default=None, help="the upper key, exclusive")
    p = sub.add_parser("find")
    p.add_argument("object_store")
    p.add_argument("index", help="an index type or name, e.g. 31:by-status or by-status")
    p.add_argument("key")
    p = sub.add_parser("blob")
    p.add_argument("kind", help="the blobs/ subdirectory, e.g. dispatch")
    p.add_argument("name", help="the file name, e.g. dispatch-20261012-162054-8fd0d9d0.md")
    p = sub.add_parser("blobs")
    p.add_argument("kind", nargs="?", default=None, help="only this blobs/ subdirectory")
    sub.add_parser("check")
    sub.add_parser("engine")
    sub.add_parser("pool-diff")
    sub.add_parser("digest")
    args = ap.parse_args()
    store = os.path.abspath(args.store)
    now = getattr(args, "now", None) or datetime.datetime.now().strftime(NOW_FMT)
    if args.cmd == "sync":
        return cmd_sync(store, args.session, now, args.full, args.budget_s)
    if args.cmd == "light":
        return cmd_light(store, args.session, now, args.dry, args.budget_s)
    if args.cmd == "pour":
        return cmd_pour(store, args.session, now, args.specs, args.dry, args.archive)
    if args.cmd == "archive":
        return cmd_archive(store, args.session, now, args.dry)
    if args.cmd == "compact":
        return cmd_compact(store, args.session, now, args.force)
    if args.cmd == "migrate":
        return cmd_migrate(store, args.session, now, args.dry, args.shadow, args.budget_s)
    if args.cmd == "rollback":
        return cmd_rollback(store, args.session, now, args.dry)
    if args.cmd == "pool-stamp":
        return cmd_pool_stamp(store, now)
    if args.cmd == "get":
        return cmd_get(store, args.object_store, args.key)
    if args.cmd == "range":
        return cmd_range(store, args.object_store, args.lo, args.hi)
    if args.cmd == "find":
        return cmd_find(store, args.object_store, args.index, args.key)
    if args.cmd == "blob":
        return cmd_blob(store, args.kind, args.name)
    if args.cmd == "blobs":
        return cmd_blobs(store, args.kind)
    if args.cmd == "check":
        return cmd_check(store)
    if args.cmd == "engine":
        engine, setting, state = resolve(store)
        print(f"engine: {engine} (index-engine: {setting}; the store: {state})")
        return 0
    if args.cmd == "pool-diff":
        print(pool_diff(store))
        return 0
    if args.cmd == "digest":
        print(keyspace_digest(store) if resolve(store)[0] == "idb" else (phi_engine_line(store) or "engine: phi"))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
