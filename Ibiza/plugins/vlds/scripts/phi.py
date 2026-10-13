#!/usr/bin/env python3
"""phi.py — the VLDS φ-register's mechanical companion.

Deterministic and judgment-free, in the p4.py mold: it checks, computes, and verifies; it never decides
what deserves keeping, never sweeps on its own, and never deletes anything. The model (the gc, in-session)
judges; this script is the arithmetic and the scans.

Subcommands:
  check         run the eleven structural scans over the store; report, never repair (exit 1 = corruption,
                exit 0 = clean, debt-only, or stray-only — '2'/'11' states are owed work, not corruption;
                a [STRAY] is a store-named, store-shaped file found OUTSIDE the store, to depth 2 under
                the project root, owed a re-home the user performs; shape drift is notes-only, because
                an off-schema entry can be the user's edit — a ruling). A store on the keyspace
                (idb/keys.tsv) is handed to scripts/idb.py check, which runs its own scans and this
                one's store-level scans with it.
  mask          retired: naming what is cold is the sweep moment's judgment, by head line; no score grid
  verify-merge  the merge deletion gate: every parent entry body must be verbatim-contained in the
                child, and the child may not exceed its parents' bytes (override with --allow-growth)
  verify-pour   the trim deletion gate: every entry body in a hot file's mask=A:B span must be
                verbatim-contained in the target segment before the span may be trimmed
  lock/unlock   the sweep lock (arc/.sweep-lock, session-stamped, stale after 60 minutes) — taken
                before any arc write; without it a session only reports owed work
  rebuild       regenerate phi-index.md from segment headers + store grammar — corruption recovery ONLY:
                refuses to run while the drift scan shows a voided watermark (a user edit is a ruling);
                on a store on the keyspace, `idb.py sync --full` is the rebuild
  restore       print a segment's entries to stdout for judged re-insertion
  lint          the tier guard: scan the PLUGIN's own doctrine files for store-tier content that leaked
                into the portable layer — session dates, "per the user" attributions, dated rulings,
                session-id tokens. Doctrine states mechanism; provenance lives in the store, which
                recall replays. Report-only; the model judges each hit.
  barrier       the read barrier's mechanical half: every entry of the read list stamped LIVE / SPENT /
                FREED / EXPIRED by rule alone — its own status field, a tombstone's mask (the same
                owner-words, or a head contained in the tombstone's freed:), a virtual entry minted by
                another session, a cleared task — the masked spans skipped; one line per entry
                (`<file>:<line>  <STATE>  <time>  <head> — <reason>`, the prefix a pool child copies
                verbatim), or --json. Ownership is not traced here: a rule or claim with no user ruling at
                its root is a reading, the pool composer's UNOWNED call, never this script's.
  pool          the recall pool's skeleton from the barrier's own rows, in one pass and with no model reading
                a file: standing (form and every-turn lines first, never grouped; the rest one per line, grouped
                by file only when the cap forces it), open (live tasks, this session's inferences, the index's
                debts), surfaced (SPENT / FREED / EXPIRED with the mask's source) and read-on-demand — and an
                empty steering section for the operator's one judged pass. --session, --task, --now required.
  trace         the write barrier's mechanical half, run by the post-write and turn-close hooks: every hot
                entry whose head is new since the last trace (store/.gc-heads, the remembered set) is an
                allocation traced against the tombstone masks — a new entry a tombstone masks, dated no
                earlier than the free, is freed garbage allocated again; a new tombstone's reach is listed
                with the LIVE entries that hold a handle to what it freed (the head's opening 32 characters
                verbatim in a field, or a field that is wholly a verbatim quote from within the head),
                each owed its pre-finalizer that turn. One
                `gc:` line per finding; the first trace on a store records a baseline. --dry, --json.

Watermark convention (shared by reader and writer, pinned in gc/reference.md): `mask=A:B sha=H` is a
0-based, HALF-OPEN line range — the masked span is lines[A:B]; live entries are counted outside it.

Conventions (pinned in gc/reference.md "The φ-register"):
  positions are 1-based over the package cache CACHE = [1, 2, 3, 5, 8, ...]; position p has weight
  CACHE[p-1] and byte capacity CACHE[p-1] KB. Epoch pairs are (CACHE[k], CACHE[k+1]); Cassini
  b^2 - a*b - a^2 == (-1)^k holds under cache indexing and flips sign under any odd shift — the
  position-weight numbering must not be reused for the epoch check.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import partition as pt  # noqa: E402 — the p4 layout: one store per session, read across by merged_entries()

CACHE = [1, 2]
while len(CACHE) < 40:
    CACHE.append(CACHE[-1] + CACHE[-2])

SEED_HOT = ["local-storage.md", "index.md", "data-store.md", "ledger.md", "tombstones.md",
            "virtual.md", "session-storage.md", "logger.md", "briefs.md"]
# every name the store owns — the same set as hooks/vlds_hooks.py STORE_FILES; a file carrying one of these
# names outside the store, holding store-shaped entries, is the [STRAY] class (found live: a ledger entry
# appended to a repo root because the bare name had been true under an earlier fence's cd)
STORE_FILES = set(SEED_HOT) | {"dispatch.md", "phi-index.md", "recall-pool.md"}
STRAY_SKIP = {".git", "node_modules", "build", "third_party", "__pycache__"}
STRAY_DEPTH = 2
STRAY_ENTRY_RE = re.compile(r"^- [a-z-]+: ")
LIVENESS_HORIZON_S = 24 * 3600
FACT_ID_RE = re.compile(r"^id: ([a-z]{2}-\d{4})( \(tombstoned\))?\s*$", re.M)
SEG_NAME_RE = re.compile(r"^arc-(\d+)-([A-Za-z0-9]+)\.md$")
POURED_DISPATCH_RE = re.compile(r"^dispatch-\d{8}-\d{6}-[0-9A-Za-z-]{1,12}\.md$")  # the prompt hook's pour — the tail is the owner session's short id
RUN_FILE_RE = re.compile(r"^[a-z][a-z-]*-\d{6,}\.md$")    # a keyspace run, scripts/idb.py's RUN_NAME_RE
LOGGER_ENTRY_RE = re.compile(r"^- `\[(?:gate|guide|gc|inspector|looper)\]` 20\d\d-\d\d-\d\d(?: \d\d:\d\d)? — \*\*")


def on_keyspace(store):
    """True when the store is on the keyspace — idb/keys.tsv, or runs whose keys.tsv is gone: scripts/idb.py's rule."""
    if os.path.exists(os.path.join(store, "idb", "keys.tsv")):
        return True
    runs = os.path.join(store, "idb", "runs")
    return os.path.isdir(runs) and any(RUN_FILE_RE.match(n) for n in os.listdir(runs))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ─── segment parsing ────────────────────────────────────────────────────────────────────────────────────

def parse_segment(path):
    """A segment = one ```yaml-fenced header block, then entry blocks delimited by column-0 '---'.
    Each entry block: an 'id: xx-NNNN' line, a blank line, then the verbatim body."""
    text = read(path)
    lines = text.split("\n")
    issues = []
    header = {}
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    # locate the fenced header
    try:
        first = next(i for i, l in enumerate(lines) if l.strip())
    except StopIteration:
        return {}, [], ["empty segment"]
    if lines[first] != "```yaml":
        issues.append("header is not a ```yaml fence (frontmatter '---' headers breach the grammar)")
        return {}, [], issues
    try:
        close = next(i for i in range(first + 1, len(lines)) if lines[i] == "```")
    except StopIteration:
        return {}, [], ["unterminated header fence"]
    for l in lines[first + 1:close]:
        m = re.match(r"^([A-Za-z-]+):\s*(.*)$", l)
        if m:
            header[m.group(1)] = m.group(2)
    # entries: split the remainder on column-0 '---'
    rest = lines[close + 1:]
    entries, cur = [], []
    for l in rest:
        if l == "---":
            if cur and any(x.strip() for x in cur):
                entries.append("\n".join(cur).strip("\n"))
            cur = []
        else:
            cur.append(l)
    if cur and any(x.strip() for x in cur):
        entries.append("\n".join(cur).strip("\n"))
    # a mid-body column-0 '---' was already consumed by the splitter above; its observable residue is
    # an id-less pseudo-entry, so flag exactly that — plus column-0 fences, which the splitter ignores
    for i, e in enumerate(entries):
        if not FACT_ID_RE.match(e.split("\n", 1)[0] + "\n"):
            issues.append(f"entry {i}: missing id line — possible mid-body '---' split")
        for l in e.split("\n")[2:]:
            if l.startswith("```"):
                issues.append(f"entry {i}: column-0 fence inside body — grammar hazard")
    return header, entries, issues


def entry_id(entry):
    m = FACT_ID_RE.match(entry.split("\n", 1)[0] + "\n")
    return m.group(1) if m else None


def entry_body(entry):
    lines = entry.split("\n")
    if lines and lines[0].startswith("id: "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).strip("\n")


# ─── phi-index parsing ──────────────────────────────────────────────────────────────────────────────────

def parse_index(store):
    path = os.path.join(store, "phi-index.md")
    if not os.path.exists(path):
        return None
    text = read(path)
    idx = {"register": "", "positions": [], "hot": [], "epochs": [], "raw": text}
    m = re.search(r"^register:\s*([01]+)", text, re.M)
    if m:
        idx["register"] = m.group(1)
    section = None
    for l in text.split("\n"):
        if l.startswith("## "):
            section = l[3:].strip()
            continue
        if not l.startswith("|") or set(l.replace("|", "").strip()) <= {"-", " ", ":"}:
            continue
        cells = [c.strip() for c in l.strip("|").split("|")]
        if section == "positions" and cells[0] != "pos":
            idx["positions"].append(cells)
        elif section == "hot" and cells[0] != "file":
            idx["hot"].append(cells)
        elif section == "epochs" and cells[0] != "file":
            idx["epochs"].append(cells)
    return idx


def hot_entry_count(store, fname, span=None):
    """Entries = column-0 '- ' lines after the header separator, excluding a masked span.
    `span` is the (A, B) half-open line range of the watermarked (poured, untrimmed) region."""
    path = os.path.join(store, fname)
    if not os.path.exists(path):
        return None
    lines = read(path).split("\n")
    try:
        start = lines.index("---") + 1
    except ValueError:
        start = 0
    a, b = span if span else (0, 0)
    return sum(1 for i, l in enumerate(lines[start:], start)
               if l.startswith("- ") and not (a <= i < b))


# ─── stray files ────────────────────────────────────────────────────────────────────────────────────────

def looks_store_shaped(path):
    """True when the first non-blank line after the file's first '---' separator (or its first line, when it
    has none) is a store entry head — `- field: `. A docs index.md opening with prose stays out."""
    try:
        text = read(path)
    except (OSError, UnicodeDecodeError):
        return False
    body = text.split("\n---\n", 1)[1] if "\n---\n" in text else text
    for l in body.split("\n"):
        if l.strip():
            return bool(STRAY_ENTRY_RE.match(l))
    return False


def stray_files(store):
    """Store-named, store-shaped files outside the store, to STRAY_DEPTH under the project root (the parent
    of `.claude`), skipping STRAY_SKIP directories, the store itself and the legacy store at `.claude/vlds`
    (the SessionStart hook's migration source, left for the user to dispose); [] when the store is not at
    `<root>/.claude/p4/sessions/<s8>/vlds`, since no project root is defined then."""
    p4 = pt.p4_of(store)
    dot = os.path.dirname(p4) if p4 else ""
    if not p4 or os.path.basename(p4) != "p4" or os.path.basename(dot) != ".claude":
        return []
    root = os.path.dirname(dot)
    store_abs = os.path.normcase(os.path.abspath(store))
    legacy_abs = os.path.normcase(os.path.join(dot, "vlds"))
    found = []

    def walk(d, depth):
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError:
            return
        for e in entries:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                if e.name in STRAY_SKIP or os.path.normcase(os.path.abspath(e.path)) in (store_abs, legacy_abs):
                    continue
                if depth < STRAY_DEPTH:
                    walk(e.path, depth + 1)
            elif e.name in STORE_FILES and looks_store_shaped(e.path):
                found.append(os.path.relpath(e.path, root))

    walk(root, 0)
    return found


# ─── legacy mask records ──────────────────────────────────────────────────────────────────────────────

def verify_mask(mask):
    prev = 0
    for v in mask:
        if v == 1 and prev == 1:
            return False
        prev = v
    return True


# ─── subcommands ────────────────────────────────────────────────────────────────────────────────────────

def cmd_check(store, delegate=True):
    if delegate and on_keyspace(store):
        import idb  # noqa: E402 — the keyspace engine beside this file; it calls back here for the store-level scans
        return idb.cmd_check(store)
    corrupt, debt, stray, notes = [], [], [], []
    arc = os.path.join(store, "arc")
    idx = parse_index(store)

    # 1. register scan — '2' (two segments at one position) and '11' (adjacent positions) are DEBT
    positions = {}
    if os.path.isdir(arc):
        for f in sorted(os.listdir(arc)):
            m = SEG_NAME_RE.match(f)
            if m:
                positions.setdefault(int(m.group(1)), []).append(f)
    for p, files in sorted(positions.items()):
        if len(files) > 1:
            debt.append(f"register '2' at position {p}: {files} — a RESOLVE is owed")
    occupied = sorted(positions)
    for a, b in zip(occupied, occupied[1:]):
        if b == a + 1:
            debt.append(f"register '11' at positions {a},{b} — a CARRY is owed")
    if idx and idx["register"]:
        derived = "".join("1" if p in positions else "0"
                          for p in range(max(occupied, default=0), 0, -1))
        if derived and derived.lstrip("0") != idx["register"].lstrip("0"):
            corrupt.append(f"index register '{idx['register']}' != derived '{derived}'")
        elif idx["register"].lstrip("0") and not occupied:
            corrupt.append("index register claims occupied positions but arc/ holds no segments")

    # positions-table cross-check — the torn-pour detector and the weight recurrence's independent witness
    if idx is not None:
        table = {}
        for row in idx["positions"]:
            try:
                p, wkb, seg_file = int(row[0]), int(row[1]), row[2]
            except (ValueError, IndexError):
                corrupt.append(f"positions row unparseable: {row}")
                continue
            table[p] = row
            if not (1 <= p <= len(CACHE)):
                corrupt.append(f"positions row names impossible position {p}")
                continue
            if wkb != CACHE[p - 1]:
                corrupt.append(f"positions row {p}: weight {wkb} KB != CACHE[{p - 1}] = {CACHE[p - 1]} KB")
            if not os.path.exists(os.path.join(arc, seg_file)):
                corrupt.append(f"positions row {p} names missing segment {seg_file}")
        for p, files in positions.items():
            if p not in table:
                corrupt.append(f"segment(s) at position {p} absent from the positions table — torn pour: "
                               f"delete and re-sweep ({files})")

    # unregistered mass — files in arc/ that are neither positioned segments, declared attachments,
    # nor the lock are outside the register entirely: owed registration or collection, invisible to
    # every other scan (found live in a peer store's bootstrap verification)
    if os.path.isdir(arc):
        registered = {f for files in positions.values() for f in files} | {".sweep-lock"}
        for p, files in positions.items():
            for f in files:
                h, _e, _i = parse_segment(os.path.join(arc, f))
                registered |= {a.strip() for a in h.get("attached", "").split(",") if a.strip()}
        for f in sorted(os.listdir(arc)):
            if f not in registered and os.path.isfile(os.path.join(arc, f)):
                if POURED_DISPATCH_RE.match(f):
                    debt.append(f"arc/{f}: hook-poured dispatch record — attachment registration owed to "
                                f"the next sweep")
                else:
                    debt.append(f"arc/{f}: unregistered file — outside the register; registration or "
                                f"collection owed (the gc judges)")

    # 2+3. per-segment: grammar, mask records, ids
    all_ids = {}
    tombstoned_ids = set()
    for p, files in sorted(positions.items()):
        for f in files:
            header, entries, issues = parse_segment(os.path.join(arc, f))
            for i in issues:
                corrupt.append(f"{f}: {i}")
            w = header.get("weight-kb")
            if w and int(w) != CACHE[p - 1]:
                corrupt.append(f"{f}: header weight {w} KB != position weight {CACHE[p - 1]} KB")
            size = os.path.getsize(os.path.join(arc, f))
            cap = CACHE[p - 1] * 1024
            for att in [a.strip() for a in header.get("attached", "").split(",") if a.strip()]:
                ap = os.path.join(arc, att)
                if os.path.exists(ap):
                    size += os.path.getsize(ap)
                else:
                    corrupt.append(f"{f}: attached file {att} missing from arc/")
            if size > cap:
                debt.append(f"{f}: position bytes {size} > capacity {cap} — settling owed")
            if header.get("mask"):
                if not verify_mask([int(c) for c in header["mask"] if c in "01"]):
                    corrupt.append(f"{f}: recorded mask contains adjacent keeps")
            if "verified" not in header:
                corrupt.append(f"{f}: no 'verified:' commit mark — treat as a torn pour (dead to recall)")
            for e in entries:
                m_id = FACT_ID_RE.match(e.split("\n", 1)[0] + "\n")
                if m_id:
                    all_ids.setdefault(m_id.group(1), []).append(f)
                    if m_id.group(2):
                        tombstoned_ids.add(m_id.group(1))

    # 5. uniqueness — one fact-id, one live segment
    for eid, where in sorted(all_ids.items()):
        if len(set(where)) > 1:
            corrupt.append(f"fact-id {eid} live in {sorted(set(where))} — one fact, one place violated")

    # 4. epochs — Cassini + row-to-row continuity
    if idx:
        for row in idx["epochs"]:
            try:
                fname, k, a, b = row[0], int(row[1]), int(row[2]), int(row[3])
            except (ValueError, IndexError):
                corrupt.append(f"epochs row unparseable: {row}")
                continue
            if not (0 <= k < len(CACHE) - 1):
                corrupt.append(f"epoch k={k} for {fname} out of range — corrupt counter")
                continue
            if b * b - a * b - a * a != (-1) ** k:
                corrupt.append(f"epoch pair ({a},{b}) for {fname} falls off the Fibonacci lattice")
            if (a, b) != (CACHE[k], CACHE[k + 1]):
                corrupt.append(f"epoch k={k} for {fname}: pair ({a},{b}) != (CACHE[{k}],CACHE[{k+1}]) — "
                               f"continuity broken (skipped or repeated epoch)")

    # 7. drift — recount hot rows; hash below-watermark spans against their recorded pour hashes
    if idx:
        for row in idx["hot"]:
            fname = row[0]
            wm = row[5] if len(row) > 5 else "—"
            span, wm_hash = None, None
            m = re.match(r"mask=(\d+):(\d+)\s+sha=([0-9a-f]+)", wm)
            if m:
                span, wm_hash = (int(m.group(1)), int(m.group(2))), m.group(3)
            count = hot_entry_count(store, fname, span)
            if count is None:
                corrupt.append(f"hot row names missing file {fname}")
                continue
            try:
                live = int(row[1])
                if live != count:
                    notes.append(f"{fname}: index live={live}, recounted {count} — stale row (updates at sweep)")
            except (ValueError, IndexError):
                pass
            # the pressure verdict — recomputed here at recall, as the doctrine promises: the stored
            # row updates only at sweep, so the RECOUNT carries the live verdict
            try:
                budget = int(row[4])
                if count > budget:
                    debt.append(f"{fname}: {count} entries over budget {budget} — normalize owed")
            except (ValueError, IndexError):
                pass
            try:
                at_sweep = int(row[2])
                # dispatch.md is exempt: the prompt hook pours it whole-file at a new session's first prompt,
                # so its growth is never the sweep's to settle
                if fname != "dispatch.md" and at_sweep > 0 and count / at_sweep >= 1.618:
                    debt.append(f"{fname}: live/at-sweep = {count}/{at_sweep} ≥ φ — pressure owed")
            except (ValueError, IndexError):
                pass
            if span and wm_hash:
                # the masked span is lines[A:B], half-open, 0-based — the one shared definition
                masked = "\n".join(read(os.path.join(store, fname)).split("\n")[span[0]:span[1]])
                if sha(masked) != wm_hash:
                    corrupt.append(f"WATERMARK VOIDED on {fname}: the user ruled inside the masked span — "
                                   f"the gc must reconcile before the arc copy may be cited")

    # 6. duplication — verbatim >60-char lines in two hot files ('11' suspects, judged by the gc)
    seen = {}
    for fname in SEED_HOT:
        path = os.path.join(store, fname)
        if not os.path.exists(path):
            continue
        for l in read(path).split("\n"):
            s = l.strip()
            if len(s) > 60 and not s.startswith("#"):
                seen.setdefault(s, set()).add(fname)
    for s, files in seen.items():
        if len(files) > 1:
            notes.append(f"verbatim line in {sorted(files)}: {s[:70]}...")

    # 8. owed borrows — tombstoned fact-ids still live in canonical blocks. An id annotated
    # `(tombstoned)` on its own id line is exempt: the pour class deliberately archives already-
    # tombstoned bodies, and the tombstone plus the annotation together read "freed, archived, not
    # steering" — without the annotation the scan cannot tell archived history from a lurking free
    tpath = os.path.join(store, "tombstones.md")
    if os.path.exists(tpath):
        for eid in set(re.findall(r"\b([a-z]{2}-\d{4})\b", read(tpath))):
            if eid in all_ids and eid not in tombstoned_ids:
                debt.append(f"'-1' state: tombstoned {eid} still live in {all_ids[eid]} — a BORROW is owed "
                            f"(or the id line lacks its '(tombstoned)' annotation, if this was a pour)")

    # 9. liveness — dispatch.md is the live dispatcher (the floor): poured whole-file by the prompt hook at
    # a new session's first prompt, never by this script. Per-session dispatch-*.md files in the store ROOT
    # are legacy artifacts of the pre-0.0.18 design, still judged by age + content while an old-contract
    # session could yet exist.
    now = time.time()
    if os.path.exists(os.path.join(store, "dispatch.md")):
        notes.append("dispatch.md: the live dispatcher — untouchable by script; the prompt hook pours it")
    else:
        debt.append("dispatch.md missing — the hook seeds it; until then the dispatch floor has no target")
    for f in sorted(os.listdir(store)):
        if f.startswith("dispatch-") and f.endswith(".md"):
            age = now - os.path.getmtime(os.path.join(store, f))
            if age < LIVENESS_HORIZON_S:
                notes.append(f"{f}: legacy per-session record inside the {LIVENESS_HORIZON_S // 3600}h horizon — hold")
            else:
                notes.append(f"{f}: legacy per-session record, dead candidate (age + content; the gc judges)")

    # 10. conformance — each hot file's entries against the shape its OWN header declares (the file
    # is the shape's authority). Drift is notes-only: an off-schema entry can be the user's hand
    # edit, which is a ruling, so repair is judged, never mechanical.
    for fname in SEED_HOT + ["dispatch.md"]:
        path = os.path.join(store, fname)
        if not os.path.exists(path):
            continue
        text = read(path)
        if "\n---\n" not in text:
            # a separator-less file used to be silently skipped here — the exact blind spot that hid a
            # whole store's pre-canonical files from this scan
            if any(l.startswith("- ") for l in text.split("\n")):
                notes.append(f"{fname}: entries but no header/entries separator — pre-canonical "
                             f"structure, normalize owed")
            continue
        head, body = text.split("\n---\n", 1)
        hm = re.search(r"```yaml\n(.*?)```", head, re.S)
        if hm and re.search(r"^- [a-z-]+:", hm.group(1), re.M) and "[" not in hm.group(1):
            notes.append(f"{fname}: header fence holds live entries, not a shape template — "
                         f"normalize owed")
        wrapped = sum(1 for l in body.split("\n") if re.match(r"^    \S", l))
        if wrapped:
            notes.append(f"{fname}: {wrapped} wrapped continuation line(s) — one field = one line, "
                         f"normalize owed")
        if fname == "logger.md":
            for i, l in enumerate(body.split("\n"), 1):
                if l.startswith("- ") and not LOGGER_ENTRY_RE.match(l):
                    notes.append(f"{fname}: line {i} diverges from the tagged-bullet shape — judged repair")
            continue
        m = re.search(r"```yaml\n(.*?)```", head, re.S)
        if not m:
            continue
        allowed = set(re.findall(r"^(?:- |  )([a-z-]+):", m.group(1), re.M))
        if not allowed:
            continue
        for i, l in enumerate(body.split("\n"), 1):
            mm = re.match(r"^- ([a-z-]+):", l) or re.match(r"^  ([a-z-]+):", l)
            if mm and mm.group(1) not in allowed:
                notes.append(f"{fname}: line {i} field '{mm.group(1)}' not in the header shape — judged repair")

    # 11. stray — a store-named, store-shaped file outside the store: written to a bare path that was true
    # under another fence's cd, it is nobody's finding unless something looks beyond the store. Reported, never
    # moved: the user re-homes it (or says it is not VLDS state and renames it).
    for rel in stray_files(store):
        stray.append(f"{rel}: store-shaped file outside the store — re-home into "
                     f"{os.path.join(store, os.path.basename(rel))} or rename")

    for tag, items in (("CORRUPT", corrupt), ("DEBT", debt), ("STRAY", stray), ("note", notes)):
        for i in items:
            print(f"[{tag}] {i}")
    print(f"phi.py check: {len(corrupt)} corruption, {len(debt)} debt, {len(stray)} stray, {len(notes)} notes")
    return 1 if corrupt else 0


def cmd_verify_merge(args):
    child = read(args.child)
    ok = True
    total_parent_bytes = 0
    for p in args.parents:
        text = read(p)
        total_parent_bytes += len(text.encode("utf-8"))
        _, entries, _ = parse_segment(p)
        blocks = entries if entries else [text]
        for e in blocks:
            body = entry_body(e)
            if body and body not in child:
                ok = False
                print(f"FAIL: parent {os.path.basename(p)} entry not verbatim-contained: {body[:60]}...")
    child_bytes = len(child.encode("utf-8"))
    if child_bytes > total_parent_bytes:
        # merges may only shrink — growth on a deletion gate is a FAIL unless explicitly overridden
        if args.allow_growth:
            print(f"note: child {child_bytes} B > parents {total_parent_bytes} B — allowed by --allow-growth")
        else:
            ok = False
            print(f"FAIL: child {child_bytes} B > parents {total_parent_bytes} B — merges may only shrink")
    print("PASS — parents may be deleted (mark the child 'verified:' FIRST; that is the commit point)"
          if ok else "FAIL — do not delete parents")
    return 0 if ok else 1


def split_span_bodies(lines):
    """Split a hot-file span into entry bodies on column-0 '- ' / '#' starts (the store grammar)."""
    bodies, cur = [], []
    for l in lines:
        if l.startswith("- ") or l.startswith("#"):
            if cur and any(x.strip() for x in cur):
                bodies.append("\n".join(cur).rstrip())
            cur = [l]
        else:
            cur.append(l)
    if cur and any(x.strip() for x in cur):
        bodies.append("\n".join(cur).rstrip())
    return bodies


def cmd_verify_pour(args, store):
    """The trim gate: every entry body in the hot file's mask=A:B span must live verbatim in the segment."""
    seg_text = read(args.segment) if os.path.isabs(args.segment) \
        else read(os.path.join(store, "arc", args.segment))
    a, b = (int(x) for x in args.span.split(":"))
    src_lines = read(os.path.join(store, args.source)).split("\n")[a:b]
    ok = True
    bodies = split_span_bodies(src_lines)
    for bd in bodies:
        if bd.strip() and bd not in seg_text:
            ok = False
            print(f"FAIL: span body not verbatim-contained in segment: {bd[:60]!r}")
    print(f"checked {len(bodies)} bodies from {args.source}[{a}:{b}]")
    print("PASS — the span may be trimmed" if ok else "FAIL — do not trim")
    return 0 if ok else 1


def cmd_lock(args, store, release=False):
    """The sweep lock: session-stamped, stale after 60 minutes; taken before any arc write."""
    if on_keyspace(store):
        print("REFUSED: the store is on the keyspace — its lock is idb/.sweep-lock, which idb.py takes itself")
        return 1
    lock = os.path.join(store, "arc", ".sweep-lock")
    if release:
        if not os.path.exists(lock):
            print("no lock held")
            return 0
        holder = read(lock).split()[0]
        if holder != args.session:
            print(f"REFUSED: lock held by {holder}, not {args.session}")
            return 1
        os.remove(lock)
        print("released")
        return 0
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    if os.path.exists(lock):
        age = time.time() - os.path.getmtime(lock)
        holder = read(lock).split()[0]
        if holder != args.session and age < 3600:
            print(f"REFUSED: fresh lock held by {holder} ({int(age)} s old) — report owed work instead")
            return 1
        print(f"superseding {'own' if holder == args.session else 'stale'} lock ({holder}, {int(age)} s)")
    with open(lock, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{args.session} {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    print("granted")
    return 0


def cmd_rebuild(store):
    # corruption recovery ONLY: a voided watermark is a user ruling this script must not pave over
    if on_keyspace(store):
        print("rebuild: the store is on the keyspace — `idb.py sync --full` rebuilds idb/keys.tsv from the files")
        return 0
    class Silent:
        def write(self, *_):
            pass
        def flush(self):
            pass
    real = sys.stdout
    sys.stdout = Silent()
    try:
        rc = cmd_check(store)
    finally:
        sys.stdout = real
    if rc != 0:
        print("rebuild refused: check reports corruption — reconcile rulings and torn pours first "
              "(a user edit outranks a recomputation)")
        return 1
    print("rebuild: derive the index from arc/ headers and hot recounts, then compare with the model "
          "in-session; this script intentionally does not write phi-index.md unattended — emit follows:")
    arc = os.path.join(store, "arc")
    if os.path.isdir(arc):
        for f in sorted(os.listdir(arc)):
            m = SEG_NAME_RE.match(f)
            if m:
                print(f"position {int(m.group(1))}: {f} "
                      f"({os.path.getsize(os.path.join(arc, f))} B)")
    for fname in SEED_HOT:
        c = hot_entry_count(store, fname)
        if c is not None:
            print(f"hot {fname}: {c} entries, {os.path.getsize(os.path.join(store, fname))} B")
    return 0


def cmd_restore(args):
    header, entries, issues = parse_segment(args.segment)
    for i in issues:
        print(f"[grammar] {i}", file=sys.stderr)
    for e in entries:
        print("---")
        print(e)
    return 0


LINT_PATTERNS = [
    (re.compile(r"\b20\d\d-\d\d(-\d\d)?\b"), "session date in portable doctrine"),
    (re.compile(r"per the user", re.I), "user attribution in portable doctrine"),
    (re.compile(r"\bruling\b[^.\n]{0,20}\b20\d\d\b|\b20\d\d\b[^.\n]{0,20}\bruling\b", re.I),
     "dated ruling citation in portable doctrine"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}\b"), "session-id token in portable doctrine"),
]
LINT_EXEMPT = {"examples.md"}  # worked examples legitimately carry illustrative dates


# ─── the read barrier, mechanical ───────────────────────────────────────────────────────────────────────

BARRIER_STATES = ("LIVE", "SPENT", "FREED", "EXPIRED")
BARRIER_DEFAULT_FILES = ["local-storage.md", "index.md", "tombstones.md", "ledger.md", "session-storage.md",
                         "virtual.md", "briefs.md", "data-store.md", "logger.md"]
BARRIER_HEAD_CHARS = 140
MASK_MIN = 24                 # the shorter side of a head/freed containment must be this long to count as a mask
HOT_HEAD_RE = re.compile(r"^- ([a-z-]+):\s*(.*)$")
HOT_FIELD_RE = re.compile(r"^  ([a-z-]+):\s*(.*)$")
CLEARED_RE = re.compile(r"^(complete|completed|done|cleared|closed)\b", re.I)
SESSION_ID_RE = re.compile(r"[0-9a-f]{8}")


def norm_text(v):
    """A field value normalized for matching: quotes and a trailing ellipsis off, whitespace collapsed, lower case."""
    v = v.strip().strip('"').strip("'").rstrip("…").strip()
    return re.sub(r"\s+", " ", v).lower()


def hot_entries(store, fname, span=None):
    """[(line 1-based, field, value, fields)] — the column-0 '- ' heads after the header separator, each with its
    two-space continuation fields (first occurrence wins), the masked span skipped; a logger bullet is an entry
    whose field is 'log' and whose value is the line past its dash. None when the file is absent."""
    path = os.path.join(store, fname)
    if not os.path.exists(path):
        return None
    lines = read(path).split("\n")
    try:
        start = lines.index("---") + 1
    except ValueError:
        start = 0
    a, b = span if span else (0, 0)
    out, i = [], start
    while i < len(lines):
        l = lines[i]
        if not l.startswith("- ") or a <= i < b:
            i += 1
            continue
        m = HOT_HEAD_RE.match(l)
        field, value = (m.group(1), m.group(2)) if m else ("log", l[2:])
        fields, j = {}, i + 1
        while j < len(lines) and lines[j].startswith("  "):
            fm = HOT_FIELD_RE.match(lines[j])
            if fm and fm.group(1) not in fields:
                fields[fm.group(1)] = fm.group(2)
            j += 1
        out.append((i + 1, field, value, fields))
        i = j
    return out


def merged_entries(store, fname):
    """(entries, segments) — hot_entries() across every session store a read of `fname` covers (scripts/partition.py:
    this session's alone for a session-local file, every session's for the rest), each store's own masked span
    skipped. Lines are VIRTUAL: the session files are laid end to end in session order, so a line names one entry
    across them and every caller that keys on (file, line) — the barrier, the picks, the pool — works unchanged;
    `segments` [(label, first, last)] maps a virtual line back to its session's file. Outside the p4 layout it is
    hot_entries() of the store itself, lines unchanged. entries is None when no session holds the file."""
    out, segs, offset = [], [], 0
    for s, lb in pt.expand(store, fname):
        path = os.path.join(s, fname)
        if not os.path.exists(path):
            continue
        got = hot_entries(s, fname, masked_spans(s).get(fname)) or []
        n = len(read(path).split("\n"))
        out += [(line + offset, field, value, fields) for line, field, value, fields in got]
        segs.append((lb, offset + 1, offset + n))
        offset += n
    return (out if segs else None), segs


def segment_note(store, files):
    """One line mapping the virtual lines of the files a merged read spans more than one session for, or ''."""
    if not pt.partitioned(store):
        return ""
    parts = []
    for fname in files:
        segs = merged_entries(store, fname)[1]
        if len(segs) > 1:
            parts.append(f"{fname} " + ", ".join(f"{a}-{b}={lb.split('/')[0]}" for lb, a, b in segs))
    return ("sessions (virtual lines → session directory): " + "; ".join(parts)) if parts else ""


def recall_files(store):
    """The read list from the config index's `## recall` section — inject then digest — or the barrier's default."""
    idx = parse_index(os.path.dirname(pt.config_index(store)))
    if not idx:
        return list(BARRIER_DEFAULT_FILES)
    inject, digest, in_recall = [], [], False
    for l in idx["raw"].split("\n"):
        if l.startswith("## "):
            in_recall = l[3:].strip().lower() == "recall"
            continue
        m = re.match(r"^(inject|digest):\s*(.*)$", l.strip()) if in_recall else None
        if m:
            names = [n.strip() for n in m.group(2).split(",") if n.strip()]
            if m.group(1) == "inject":
                inject = names
            else:
                digest = names
    return (inject + digest) or list(BARRIER_DEFAULT_FILES)


def masked_spans(store):
    """{file: (A, B)} — the hot table's watermarked spans, lines[A:B], which no reader opens."""
    idx = parse_index(store)
    spans = {}
    if not idx:
        return spans
    for row in idx["hot"]:
        for cell in row[1:]:
            m = re.match(r"mask=(\d+):(\d+)", cell)
            if m:
                spans[row[0]] = (int(m.group(1)), int(m.group(2)))
    return spans


def tombstone_masks(store, span=None):
    """[(ref, freed, owner-words, time)] — every tombstone, normalized: the mask the barrier applies. A hot tombstone
    is located by its line; on a keyspace store the cold ones join it, located by id (cold_tombstone_masks), so a
    mask outlives the pour or archive that moved its tombstone into the runs."""
    out = []
    hot = merged_entries(store, "tombstones.md")[0] if pt.partitioned(store) else hot_entries(store, "tombstones.md", span)
    for line, field, value, fields in (hot or []):
        if field == "freed":
            out.append((line, norm_text(value), norm_text(fields.get("owner-words", "")), fields.get("time", "")))
    for s in pt.session_stores(store):
        if on_keyspace(s):
            out += cold_tombstone_masks(s)
    return out


def cold_tombstone_masks(store):
    """[(ref, freed, owner-words, time)] for every tombstone the keyspace holds in its runs, read through idb.py's
    validated reader (the record's run and line, a wrapped body unwrapped) — the same masks idb.py's mark_freed applies
    to the cold tier, here applied to the hot one. The ref is '<id> (cold)'; it never equals a hot line number, so the
    write barrier's trace always counts a cold mask among the old ones. An unreadable keyspace yields none: the check
    reports it, and the hot masks still apply."""
    import idb  # noqa: E402 — the keyspace engine beside this file; imported late, since it imports this module
    try:
        ks, _how = idb.load_keys(store)
    except Exception:  # noqa: BLE001
        return []
    cache, out = idb.RunCache(store), []
    for (_o, pk), r in sorted(ks.cold("tombstones").items()):
        e = cache.entry(r["at"])
        if e is None:
            continue
        field, value, fields = idb.parse_block(idb.unwrap(store, e.body))
        if field == "freed":
            out.append((f"{r.get('id') or pk} (cold)", norm_text(value), norm_text(fields.get("owner-words", "")),
                        fields.get("time", "")))
    return out


def tombstone_hit(value, fields, masks):
    """(ref, time, why) for the first tombstone that masks an entry — the same owner-words, or a head contained in its
    freed: (or the reverse), the shorter side at least MASK_MIN characters — or None. `masks` is tombstone_masks()'
    shape; its first element is whatever the caller locates a tombstone by (a line here, a key in idb.py)."""
    head, own = norm_text(value), norm_text(fields.get("owner-words", ""))
    for ref, freed, words, when in masks:
        if own and words and own == words:
            return ref, when, "the same owner-words"
        short, long_ = (head, freed) if len(head) <= len(freed) else (freed, head)
        if len(short) >= MASK_MIN and short in long_:
            return ref, when, "head within its freed:"
    return None


def barrier_state(fname, field, value, fields, session, masks):
    """(STATE, reason) by the read barrier's rules, judgment-free: a `status:` field is the entry's own word;
    a tombstone masks what it freed — the same owner-words, or a head contained in its freed: (or the reverse), the
    shorter side at least MASK_MIN characters — and tombstones themselves are the mask, never masked; a virtual.md
    entry minted by another session, naming no session, or already expired or promoted is EXPIRED, as is a
    session-storage.md task whose state reads cleared; everything else is LIVE. Ownership is not traced here."""
    status = fields.get("status", "").strip().upper().split(" ")[0] if fields.get("status") else ""
    if status in ("SPENT", "FREED"):
        return status, "its own status field"
    if fname == "tombstones.md":
        return "LIVE", "the mask itself"
    hit = tombstone_hit(value, fields, masks)
    if hit:
        line, when, why = hit
        return "FREED", f"masked by tombstones.md:{line} ({when}) — {why}"
    if fname == "virtual.md":
        disp = fields.get("disposition", "").strip().lower()
        if disp.startswith("expired") or disp.startswith("promoted"):
            return "EXPIRED", f"disposition: {disp.split(' ')[0]}"
        ids = SESSION_ID_RE.findall(fields.get("minted", "").lower())
        if session and ids and session[:8].lower() not in ids:
            return "EXPIRED", f"minted by another session ({ids[0]})"
        if session and not ids:
            return "EXPIRED", "minted: names no session id — fail-closed, past its turn"
    if fname == "session-storage.md" and CLEARED_RE.match(fields.get("state", "").strip()):
        return "EXPIRED", f"state: {fields.get('state', '').strip()}"
    if status == "LIVE":
        return "LIVE", "its own status field"
    return "LIVE", "no status, no mask"


STAMP_RE = re.compile(r"\b(20\d\d-\d\d-\d\d(?: \d\d:\d\d)?)\b")
EVERY_TURN_RE = re.compile(r"\b(every|each) (closing|turn|reply)\b|\bat every\b", re.I)
KIND_BY_FILE = {"data-store.md": "claim", "virtual.md": "inference", "session-storage.md": "task",
                "briefs.md": "ask", "tombstones.md": "freed", "logger.md": "log"}
POOL_LINE_CHARS = 150         # a skeleton line's distilled text
POOL_CAP = 8000               # the pool's cap — the harness caps a hook output at 10,000 and the pool is re-injected as one
POOL_RESERVE = 2000           # the room the skeleton leaves for the judged pass's steering lines


def entry_kind(fname, field, fields):
    """One word per entry, by rule: form (a ruling carrying form:), every-turn (an index rule whose text names
    every closing or turn), ruling, rule, claim, correction, event, inference, task, ask, freed, log."""
    if fname == "local-storage.md":
        return "form" if fields.get("form", "").strip() else "ruling"
    if fname == "index.md":
        return "every-turn" if EVERY_TURN_RE.search(" ".join(fields.values())) else "rule"
    if fname == "ledger.md":
        return "correction" if field == "correction" else "event"
    return KIND_BY_FILE.get(fname, field)


def barrier_rows(store, session, files=None):
    """(rows, files, spans, missing, masks) — every entry of the read list with its barrier state, kind and fields:
    the one read both the barrier listing and the pool skeleton are printed from."""
    files = files or recall_files(store)
    spans = masked_spans(store)
    masks = tombstone_masks(store, spans.get("tombstones.md"))
    rows, missing = [], []
    for fname in files:
        entries = merged_entries(store, fname)[0]
        if entries is None:
            missing.append(fname)
            continue
        for line, field, value, fields in entries:
            state, why = barrier_state(fname, field, value, fields, session, masks)
            head = f"- {field}: {value}" if field != "log" else f"- {value}"
            time_ = fields.get("time", "")
            if not time_ and field == "log":
                m = STAMP_RE.search(value)
                time_ = m.group(1) if m else ""
            rows.append({"file": fname, "line": line, "field": field, "value": value, "fields": fields,
                         "kind": entry_kind(fname, field, fields), "state": state,
                         "head": head[:BARRIER_HEAD_CHARS], "time": time_, "reason": why})
    return rows, files, spans, missing, masks


def cmd_barrier(args, store):
    """Every entry of the read list with its read-barrier state — the mechanical half of recall, which every pool
    reader applies and none re-judges; a state a reader disagrees with is surfaced beside the entry, never applied."""
    rows, files, spans, missing, masks = barrier_rows(store, args.session, args.file)
    if args.json:
        lean = [{k: r[k] for k in ("file", "line", "kind", "state", "head", "time", "reason")} for r in rows]
        print(json.dumps({"session": args.session, "files": files, "masked": {k: list(v) for k, v in spans.items()},
                          "missing": missing, "entries": lean}, ensure_ascii=False, indent=1))
        return 0
    print(f"barrier — store {store}, session {args.session or '(none)'}, {len(files)} file(s), "
          f"{len(masks)} tombstone mask(s)")
    note = segment_note(store, files)
    if note:
        print(note)
    for fname in files:
        if fname in missing:
            print(f"## {fname} — absent")
            continue
        mine = [r for r in rows if r["file"] == fname]
        counts = {s: sum(1 for r in mine if r["state"] == s) for s in BARRIER_STATES}
        span = spans.get(fname)
        print(f"## {fname} — {len(mine)} entries: " + ", ".join(f"{counts[s]} {s}" for s in BARRIER_STATES)
              + (f"; masked span lines {span[0]}:{span[1]} skipped" if span else ""))
        for r in mine:
            print(f"{fname}:{r['line']}  {r['state']:<7} {r['time'] or '(no time)'}  {r['head']} — {r['reason']}")
    total = {s: sum(1 for r in rows if r["state"] == s) for s in BARRIER_STATES}
    print(f"barrier: {len(rows)} entries — " + ", ".join(f"{total[s]} {s}" for s in BARRIER_STATES)
          + "; ownership not traced here — an index rule or a claim with no user ruling at its root is the "
            "composer's UNOWNED call")
    return 0


# ─── the pool skeleton, mechanical ──────────────────────────────────────────────────────────────────────

def distilled(r, width=POOL_LINE_CHARS):
    """An entry's head value as one bounded line: a logger bullet's bold headline when it has one; an index rule's
    key with its directive, so the ownership call needs no read; a claim marked sourced or unsourced from its
    verified: and source: fields, for the same reason; otherwise the value with its quotes off and its whitespace
    collapsed."""
    v = r["value"]
    f = r["fields"]
    if r["field"] == "log":
        m = re.search(r"\*\*(.+?)\*\*", v)
        v = m.group(1) if m else v
    v = re.sub(r"\s+", " ", v.strip().strip('"').strip("'")).strip()
    tag = ""
    if r["file"] == "index.md" and f.get("directive", "").strip():
        directive = re.sub(r"[ \t]+", " ", f["directive"].strip())
        v = f"{v}: {directive}"
    elif r["file"] == "data-store.md":
        # the tag survives every width: the value is cut to leave it room
        tag = " (sourced)" if f.get("verified", "").strip() or f.get("source", "").strip() else " (unsourced)"
    room = max(width - len(tag), 12)
    return (v if len(v) <= room else v[:room - 1].rstrip() + "…") + tag


PICK_RE = re.compile(r"^\s*([a-z-]+\.md):(\d+)\s*\|\|\s*bears:\s*(.+?)\s*$")
# a block's head names who picked: `picks — <file>, …` a child reader, `picks (pass) — <file>, …` the operator's own
# judged pass, written for a file no child could cover — so the pool credits the pass and never a child it did not have
PICKS_HEAD_RE = re.compile(r"^\s*picks(?:\s*\((pass)\))?\s*—\s*(?:([a-z-]+\.md)\b)?")


def read_picks(path):
    """{(file, line): clause} from a picks file — the child readers' whole output, one `<file>:<line> || bears:
    <clause>` per line; a line outside that shape (a block's head line excepted) is counted, never applied — and
    {file: {"child" | "pass"}}, who picked each file: its block's head, or a child when its pick lines have none."""
    picks, ignored, sources = {}, 0, {}
    with open(path, encoding="utf-8") as f:
        for l in f:
            m = PICK_RE.match(l)
            if m:
                picks[(m.group(1), int(m.group(2)))] = m.group(3)
                continue
            h = PICKS_HEAD_RE.match(l)
            if h:
                if h.group(2):
                    sources.setdefault(h.group(2), set()).add(h.group(1) or "child")
            elif l.strip():
                ignored += 1
    for fname, _line in picks:
        sources.setdefault(fname, {"child"})
    return picks, ignored, sources


def index_road(store):
    """The config index's `pool-road:` — children when absent or unknown."""
    idx = parse_index(os.path.dirname(pt.config_index(store)))
    if not idx:
        return "children"
    in_recall = False
    for l in idx["raw"].split("\n"):
        if l.startswith("## "):
            in_recall = l[3:].strip().lower() == "recall"
            continue
        m = re.match(r"^pool-road:\s*(\w+)", l.strip()) if in_recall else None
        if m and m.group(1).lower() in ("skeleton", "children", "single"):
            return m.group(1).lower()
    return "children"


def clip(text, width):
    """A line cut to width shows its cut: its last character an ellipsis, never a word broken silently."""
    return text if len(text) <= width else text[:width - 1].rstrip() + "…"


def pool_line(r, extra="", width=POOL_LINE_CHARS):
    return f"- [{r['file']} {r['time'] or '(no time)'} {r['state']}{extra}] {distilled(r, width)}"


def grouped_line(fname, rows, head_width):
    """One line for a file's remaining LIVE entries — the count, the span of times, and each head shortened."""
    times = sorted(t for t in (r["time"] for r in rows) if t)
    span = f"{times[0]}→{times[-1]}" if times else "undated"
    heads = "; ".join(distilled(r, head_width) for r in rows) if head_width else \
        "lines " + ", ".join(str(r["line"]) for r in rows)
    return f"- [{fname}, {len(rows)} LIVE, grouped, {span}] {heads}"


def cmd_pool(args, store):
    """The pool's skeleton, printed from the barrier's own rows in one pass: every section the pool brief keys on a
    field the barrier already read — standing (form and every-turn lines first, never grouped; the rest one per
    line, grouped by file only when the cap forces it), open (live tasks, this session's inferences, the index's
    debts), surfaced (SPENT, FREED, EXPIRED, with the mask's source) and the read-on-demand list — and one empty
    section, steering, left for the operator's judged pass — or, with --picks, filled from the child readers' picks,
    each picked entry moved into steering with its bears clause, so the children's parallel judgment lands by
    script. No model reads a file for any of it, the index included: the first line names the index's road."""
    road = index_road(store)
    rows, files, spans, missing, masks = barrier_rows(store, args.session, args.file)
    picks, ignored, sources = read_picks(args.picks) if args.picks else ({}, 0, {})

    def read_label(fname):
        # who read the file for this pool: the script alone on the skeleton road; with picks, the child or the pass
        # whose block names it, and a file no block names landed nothing — never credited to a child
        if not args.picks:
            return "script"
        return "+".join(s for s in ("child", "pass") if s in sources[fname]) if fname in sources else "none landed"
    live = [r for r in rows if r["state"] == "LIVE"]
    first = [r for r in live if r["kind"] in ("form", "every-turn") and r["file"] != "tombstones.md"]
    # a tombstone is a mask, never a steering line: a child's pick of one is dropped, as a FREED entry's is
    picked = [r for r in live if (r["file"], r["line"]) in picks and r["file"] != "tombstones.md"]
    rest = [r for r in live if r not in first and r not in picked
            and r["file"] not in ("tombstones.md", "session-storage.md", "virtual.md")]
    briefs = [r for r in rows if r["file"] == "briefs.md"]
    standing_labels, classes = {}, {}
    for r in briefs:
        label = r["fields"].get("omitted", "").strip()
        if not label:
            continue
        (standing_labels if r["fields"].get("standing", "").strip() else classes)[label] = \
            (standing_labels if r["fields"].get("standing", "").strip() else classes).get(label, 0) + 1
    briefs_line = "- [briefs.md standing] " + (
        ("standing: " + ", ".join(f"`{k}:` ×{v}" for k, v in standing_labels.items())) if standing_labels
        else "no label standing yet") + (
        ("; not standing: " + ", ".join(f"{k} ×{v}" for k, v in classes.items())) if classes else "")
    open_rows = [r for r in live if r["file"] == "session-storage.md"] + [r for r in live if r["file"] == "virtual.md"]
    debts = []
    idx = parse_index(store)
    if idx:
        for row in idx["hot"]:
            if len(row) > 6 and row[6].strip() not in ("ok", "", "—"):
                debts.append(f"- debt: {row[0]} pressure {row[6].strip()} (live {row[1]}, at-sweep {row[2]})")
        upd = next((l for l in idx["raw"].split("\n") if l.startswith("updated:")), "")
        if upd:
            debts.append(clip(f"- {upd}", POOL_LINE_CHARS))
    tomb = [r for r in rows if r["file"] == "tombstones.md"]
    counts = {}
    for r in rows:
        c = counts.setdefault(r["file"], [0, 0])
        c[0] += 1
        c[1] += r["state"] == "LIVE"
    present = [f for f in files if f not in missing]
    title = f' "{args.title}"' if args.title else ""
    derived_long = ("Derived — the skeleton written by scripts/phi.py pool from the barrier's own lines, keyed on the "
                    "register's addresses; the operator's one judged pass adds the steering clauses, the UNOWNED call "
                    "and the read-on-demand picks; re-injected by the SessionStart hook on a compact; never a second "
                    "authority — the hot files are, and an entry is re-read there before it steers a decision.")
    derived_short = ("Derived — the skeleton by scripts/phi.py pool from the barrier's lines, the steering by the "
                     "children's picks or the operator's pass; re-injected on a compact; never a second authority — "
                     "the hot files are.")

    def head_lines(compact):
        return ["# VLDS Recall Pool", "", derived_short if compact else derived_long, "",
                f"session: {args.session}{title}", f"task: {args.task}", f"pooled: {args.now}",
                "read: " + ", ".join(f"{f} ({counts.get(f, [0, 0])[0]}, {read_label(f)})"
                                     for f in files if f not in missing)
                + (("; absent: " + ", ".join(missing)) if missing else ""), "",
                "## steering — bears on the task", ""]
    placeholder = ("- (the judged pass writes this section: each standing line that bears on the task, copied here "
                   "with `; bears: <how it constrains or shapes the task>` appended — nothing else in the skeleton "
                   "changes)")

    pick_order = {k: i for i, k in enumerate(picks)}     # the child's order — the strongest first, by its brief
    kept_count = [len(picked)]

    def render(mode, head_width, width, compact, steer_width=POOL_LINE_CHARS, per_file=None, clause_width=None):
        head = head_lines(compact)
        rest_now = list(rest)
        if args.picks:
            by_file_p = {}
            for r in sorted(picked, key=lambda r: pick_order[(r["file"], r["line"])]):
                by_file_p.setdefault(r["file"], []).append(r)
            kept, dropped = [], []
            for f in files:
                lst = by_file_p.get(f, [])
                cut = lst if per_file is None else lst[:per_file]
                kept += cut
                dropped += lst[len(cut):]
            kept.sort(key=lambda r: (files.index(r["file"]), r["line"]))
            kept_count[0] = len(kept)
            rest_now = sorted(rest + [r for r in dropped if r not in first],
                              key=lambda r: (files.index(r["file"]), r["line"]))
            def clause(r):
                c = picks[(r["file"], r["line"])]
                return c if not clause_width or len(c) <= clause_width else c[:clause_width - 1].rstrip() + "…"
            steer = [pool_line(r, f", form: {r['fields']['form'].strip()}" if r["kind"] == "form" else "",
                               steer_width) + f"; bears: {clause(r)}" for r in kept] \
                or ["- none — no child named an entry that bears on the task"]
        else:
            steer = [placeholder]
        standing = ["## standing — applies whatever the task", ""] + [
            pool_line(r, f", form: {r['fields']['form'].strip()}" if r["kind"] == "form" else "", width)
            for r in first] + [briefs_line]
        if mode == "lines":
            standing += [pool_line(r, "", width) for r in rest_now]
        else:
            by_file = {}
            for r in rest_now:
                by_file.setdefault(r["file"], []).append(r)
            for f in files:
                if f in by_file:
                    standing.append(grouped_line(f, by_file[f], head_width))
        surfaced = [f"{pool_line(r, '', width)} — {r['reason']}" for r in rows if r["state"] != "LIVE"]
        if compact and tomb:
            surfaced.append(f"- [tombstones.md, {len(tomb)} masks] " + "; ".join(distilled(r, 40) for r in tomb))
        else:
            surfaced += [f"- [tombstones.md {r['time'] or '(no time)'}] masks: {distilled(r, width)}" for r in tomb]
        if compact:
            demand = ["- the files and counts are the read: line's; an entry whole by the barrier's line number, "
                      "never the file"]
        else:
            demand = [f"- {f} — {counts.get(f, [0, 0])[0]} entries, {counts.get(f, [0, 0])[1]} LIVE; an entry whole "
                      "by the barrier's line number, never the file" for f in present]
        demand.append("- (the judged pass names the entries worth re-reading whole for this task, by head line)")
        opens = [pool_line(r, "", width) for r in open_rows] + [clip(d, width + 40) for d in debts]
        tail = ["", "## open", ""] + (opens or ["- none"]) + ["", "## surfaced, not applied", ""] + \
               (surfaced or ["- none"]) + ["", "## read on demand", ""] + demand + [""]
        return "\n".join(head + steer + [""] + standing + tail)

    budget = args.cap if args.picks else args.cap - args.reserve
    stages = [("lines", 0, POOL_LINE_CHARS, False), ("grouped", 48, POOL_LINE_CHARS, False),
              ("grouped", 24, POOL_LINE_CHARS, False), ("grouped", 0, POOL_LINE_CHARS, True),
              ("grouped", 0, 110, True), ("grouped", 0, 90, True), ("grouped", 0, 70, True)]
    if args.picks:
        # the steering lines shrink last: their text first, then the weakest picks per file, the strongest kept,
        # then the clauses and the standing lines' width, down to one pick per file
        stages += [("grouped", 0, 70, True, 110), ("grouped", 0, 70, True, 90)] + \
                  [("grouped", 0, 70, True, 90, n) for n in (6, 5, 4)] + \
                  [("grouped", 0, 50, True, 70, n, 80) for n in (4, 3, 2, 1)]
    text = render(*stages[0])
    for stage in stages[1:]:
        if len(text) <= budget:
            break
        text = render(*stage)
    over = len(text) - budget
    if over > 0:
        text += f"\n(skeleton {over} characters over its budget of {budget} even fully grouped — the judged pass trims the grouped lines first)\n"
    pool_part = text
    if not args.picks:
        room = args.cap - len(text)
        pool_part = text = text.replace(
            "nothing else in the skeleton changes)",
            f"nothing else in the skeleton changes; about {room} characters of room for the steering lines under "
            f"the {args.cap} cap, so the pool is written once)", 1)
        if "grouped, " in text:
            # the judged pass must still see what it groups: every grouped entry, one line with its head, after
            # the pool's end — read once in the tool result, never written into the pool
            text += ("\n## appendix — the grouped entries, for the judged pass only: not part of the pool, which "
                     "ends at read on demand\n\n"
                     + "\n".join(f"- {r['file']}:{r['line']}  {r['time'] or '(no time)'}  {distilled(r, 110)}"
                                 for r in rest) + "\n")
    summary = (f"pool-road: {road}; pool {len(pool_part)} characters of {budget} ({len(rows)} entries, {len(live)} "
               f"LIVE, {len(first)} form/every-turn lines"
               + (f", {kept_count[0]} of {len(picked)} steering picks kept" if args.picks else "")
               + (f", {ignored} pick line(s) ignored" if ignored else "")
               + (("; picks per file: " + ", ".join(
                   f"{label} {sum(1 for f in present if read_label(f) == label)}"
                   for label in ("child", "pass", "child+pass", "none landed")
                   if any(read_label(f) == label for f in present))) if args.picks else "")
               + (f"; appendix {len(text) - len(pool_part)} characters" if len(text) > len(pool_part) else "")
               + ")" + (f" → {args.out}" if args.out else ""))
    note = segment_note(store, files)
    if note:
        summary += "\n" + note
    if args.out:
        # the pool file never carries the appendix
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(pool_part if args.picks else text)
    if args.out and not args.picks:
        print(summary)
    else:
        print(summary)
        print()
        print(pool_part if args.picks else text)
    return 0


def cmd_lint(plugin_root):
    """The tier guard: portable doctrine carries mechanism and design only — a ruling's CONTENT may
    become doctrine, but its PROVENANCE (who ruled, when, in which session) belongs to the store."""
    hits = 0
    targets = []
    for sub in ("skills", "hooks"):
        for root, _dirs, files in os.walk(os.path.join(plugin_root, sub)):
            targets += [os.path.join(root, f) for f in files if f.endswith(".md")]
    targets.append(os.path.join(plugin_root, "README.md"))
    for path in sorted(targets):
        if not os.path.exists(path) or os.path.basename(path) in LINT_EXEMPT:
            continue
        rel = os.path.relpath(path, plugin_root)
        for i, line in enumerate(read(path).split("\n"), 1):
            for pat, why in LINT_PATTERNS:
                m = pat.search(line)
                if m:
                    hits += 1
                    print(f"[leak?] {rel}:{i}: {why}: ...{line.strip()[:80]}")
                    break
    print(f"phi.py lint: {hits} candidate leak(s) — each is a finding for the model to judge, not an auto-fix")
    return 1 if hits else 0


STANDING_BUDGET = 9300      # one hook output's room for the standing rules, under the harness's 10,000 cap


def cmd_standing(args, store):
    """The owner's standing rules, whole: every LIVE form ruling and every-turn index rule, one line each and uncut,
    for the SessionStart hook to print in an output of its own — so a session holds them whatever the pool's cap
    cuts, and whether or not a conductor stands between it and the pool. `--part N` prints the Nth part when they
    outgrow one hook output; a part past the end prints nothing, and a single rule over the budget is cut there
    with a marker that says where the rest is."""
    rows, _files, _spans, _missing, _masks = barrier_rows(store, args.session)
    first = [r for r in rows if r["state"] == "LIVE" and r["kind"] in ("form", "every-turn")
             and r["file"] != "tombstones.md"]
    budget = max(400, args.budget)
    lines = []
    for r in first:
        line = pool_line(r, f", form: {r['fields']['form'].strip()}" if r["kind"] == "form" else "", 10 ** 6)
        if len(line) + 1 > budget:
            line = line[:budget - 80].rstrip() + f"… (cut at the hook-output cap; the rest is {r['file']}:{r['line']})"
        lines.append(line)
    parts, cur, size = [], [], 0
    for line in lines:
        if cur and size + len(line) + 1 > budget:
            parts.append(cur)
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        parts.append(cur)
    if args.part >= len(parts):
        return 0
    where = f", part {args.part + 1} of {len(parts)}" if len(parts) > 1 else ""
    print(f"### standing rules — the owner's {len(lines)} form rulings and every-turn rules, whole{where} "
          f"(SessionStart hook; they steer every reply whatever the task, and the pool lists them by label only)")
    print("\n".join(parts[args.part]))
    return 0


# ─── the write barrier's trace — the always-on collector's mechanical half ──────────────────────────────

GC_HEADS = ".gc-heads"        # the hot heads the last trace saw, per file: the write barrier's remembered set
REALLOC_FILES = ("local-storage.md", "index.md", "data-store.md", "virtual.md")    # where a re-learned free steers
STRONG_FILES = ("local-storage.md", "index.md", "data-store.md", "virtual.md", "session-storage.md")  # Member edges
WEAK_FILES = ("ledger.md", "logger.md", "briefs.md")       # WeakMember edges: history that cites, never swept with it
HANDLE_CHARS = 32             # a handle quotes a head from its opening, at least this many characters verbatim
TRACE_LINES = 8               # the most findings one trace prints; the rest are counted


def head_keys(es):
    """[key per entry] — the sha of each head line, `#n` on its nth repeat (the keyspace's own rule), so a head
    written again beside an identical one is a new allocation, the later line the new one."""
    count, out = Counter(), []
    for _line, field, value, _fields in es:
        h = sha(f"- {field}: {value}" if field != "log" else f"- {value}")
        count[h] += 1
        out.append(h if count[h] == 1 else f"{h}#{count[h]}")
    return out


def cites(text, head):
    """True when `text` holds a handle to the entry whose normalized head value is `head`: the head's opening
    HANDLE_CHARS characters verbatim (the whole head when it is shorter), or the text itself a verbatim quote from
    within the head — either side at least MASK_MIN characters. A paraphrase is a raw pointer: never followed."""
    t = norm_text(text)
    if len(head) < MASK_MIN or len(t) < MASK_MIN:
        return False
    return head[:HANDLE_CHARS] in t or t in head


def allocated_after(entry_time, free_time):
    """True unless the entry's own time is plainly earlier than the free's — an entry new to the trace but older than
    the tombstone (a rollback's return, an old line pasted back) is freed history, not an allocation; a missing time
    on either side, or the same day with minutes on one side only, cannot tell, and counts as after."""
    a, b = STAMP_RE.search(entry_time or ""), STAMP_RE.search(free_time or "")
    if not a or not b:
        return True
    a, b = a.group(1), b.group(1)
    if len(a) != len(b):
        a, b = a[:10], b[:10]
        if a == b:
            return True
    return a >= b


def load_heads(store):
    """{file: set of head shas} the last trace recorded, or None when no trace has run (or the file is unreadable)."""
    path = os.path.join(store, GC_HEADS)
    if not os.path.exists(path):
        return None
    try:
        data = json.loads(read(path))
        return {f: set(v) for f, v in (data.get("heads") or {}).items()}
    except (ValueError, AttributeError, TypeError):
        return None


def save_heads(store, heads):
    path = os.path.join(store, GC_HEADS)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"heads": heads}, sort_keys=True))
    os.replace(tmp, path)


def gc_trace(store, session="", record=True):
    """(findings, baseline) — the write barrier's trace. Every hot entry whose head line is new since the last trace
    (GC_HEADS) is an allocation, traced against the tombstone masks the read barrier applies:

      re-allocated  a new entry in a file that steers (REALLOC_FILES), dated no earlier than the tombstone that masks
                    it, its own status not already SPENT or FREED: freed garbage allocated again, or the owner ruled it
                    again after the free. Which one is the operator's call; until it is made, the read barrier keeps
                    the entry FREED.
      free          a new tombstone: the hot entries it masks (the dying), and the LIVE entries in STRONG_FILES that
                    hold a handle to one of them (`cites`) — each owed its pre-finalizer in the turn of the free,
                    before the reply ends: rewritten, or swept into the tombstone's swept:. Handles held from
                    WEAK_FILES are counted, never owed: history that cites a freed entry is cleared at recall.

    The first trace on a store records the heads and reports nothing — a baseline. `record` False leaves GC_HEADS as
    it was. Judgment-free: what a finding means is the operator's; this only says where the edges run."""
    spans = masked_spans(store)
    entries = {}
    for fname in SEED_HOT:
        got = merged_entries(store, fname)[0]
        if got is not None:
            entries[fname] = got
    keys = {f: head_keys(es) for f, es in entries.items()}
    current = {f: sorted(k) for f, k in keys.items()}
    seen = load_heads(store)
    if seen is None:
        if record:
            save_heads(store, current)
        return [], True
    new = {f: [e for e, k in zip(es, keys[f]) if k not in seen.get(f, set())] for f, es in entries.items()}
    masks = tombstone_masks(store, spans.get("tombstones.md"))
    fresh = {e[0] for e in new.get("tombstones.md", []) if e[1] == "freed"}
    old_masks = [m for m in masks if m[0] not in fresh]
    findings = []
    for fname in REALLOC_FILES:
        for line, field, value, fields in new.get(fname, []):
            status = fields.get("status", "").strip().upper().split(" ")[0] if fields.get("status") else ""
            if status in ("SPENT", "FREED"):
                continue
            hit = tombstone_hit(value, fields, old_masks)
            if hit and allocated_after(fields.get("time", ""), hit[1]):
                findings.append({"kind": "re-allocated", "file": fname, "line": line,
                                 "head": f"- {field}: {value}", "tombstone": hit[0], "why": hit[2]})
    for mask in (m for m in masks if m[0] in fresh):
        dying = [(f, e) for f in STRONG_FILES for e in entries.get(f, []) if tombstone_hit(e[2], e[3], [mask])]
        gone = {(f, e[0]) for f, e in dying}
        heads = [norm_text(e[2]) for _f, e in dying]
        strong, weak = [], 0
        for fname in STRONG_FILES + WEAK_FILES:
            for line, field, value, fields in entries.get(fname, []):
                if (fname, line) in gone or not heads:
                    continue
                if fname in STRONG_FILES and barrier_state(fname, field, value, fields, session, masks)[0] != "LIVE":
                    continue
                if any(cites(t, h) for t in [value, *fields.values()] for h in heads):
                    if fname in STRONG_FILES:
                        strong.append(f"{fname}:{line}")
                    else:
                        weak += 1
        findings.append({"kind": "free", "tombstone": mask[0], "dying": [f"{f}:{e[0]}" for f, e in dying],
                         "strong": strong, "weak": weak})
    if record:
        save_heads(store, current)
    return findings, False


def trace_lines(findings, limit=TRACE_LINES):
    """One `gc:` line per finding, at most `limit`, the rest counted — the lines the hooks hand to the model."""
    out = []
    for f in findings[:limit]:
        if f["kind"] == "re-allocated":
            out.append(f"gc: write barrier — {f['file']}:{f['line']} ({clip(f['head'], 90)}) is new and masked by "
                       f"tombstones.md:{f['tombstone']} ({f['why']}): freed garbage allocated again, or the owner ruled "
                       f"it again after the free — the operator's call; the read barrier keeps it FREED until then")
            continue
        where = f"a free (tombstones.md:{f['tombstone']})"
        weak = (f"; {f['weak']} weak reference{'' if f['weak'] == 1 else 's'} in history stay, cleared at recall"
                if f["weak"] else "")
        if not f["dying"]:
            out.append(f"gc: {where} masks no hot entry — what it freed lives outside the hot tier (base memory, a "
                       f"plan doc, the cold tier), where the sweep is the operator's")
        elif not f["strong"]:
            out.append(f"gc: {where} reaches {', '.join(f['dying'][:4])}{' …' if len(f['dying']) > 4 else ''} and no "
                       f"live entry holds a handle to them — the sweep's inbound half is clean{weak}")
        else:
            out.append(f"gc: {where} reaches {', '.join(f['dying'][:4])}{' …' if len(f['dying']) > 4 else ''} — "
                       f"held by {', '.join(f['strong'][:6])}{' …' if len(f['strong']) > 6 else ''}: each one's "
                       f"pre-finalizer is owed this turn, before the reply ends — rewrite it, or sweep it into the "
                       f"tombstone's swept:{weak}")
    if len(findings) > limit:
        out.append(f"gc: … and {len(findings) - limit} more — `phi.py barrier` shows every FREED state")
    return out


def cmd_trace(args, store):
    findings, baseline = gc_trace(store, args.session, record=not args.dry)
    if args.json:
        print(json.dumps({"baseline": baseline, "findings": findings}, ensure_ascii=False, indent=1))
        return 0
    if baseline:
        print("gc: write barrier — first trace on this store; the heads are recorded, nothing reported")
    for line in trace_lines(findings):
        print(line)
    return 0


def main():
    # the store is UTF-8; Windows consoles default to a legacy codepage, which made restore crash on
    # '→' and check print mojibake — force UTF-8 out, replacing anything a weirder console still rejects
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="phi.py", description="VLDS φ-register mechanical companion")
    ap.add_argument("--store", default=os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."),
                                                    ".claude", "p4", "vlds"))
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("check")
    sub.add_parser("mask", help="retired")
    p = sub.add_parser("verify-merge")
    p.add_argument("--child", required=True)
    p.add_argument("--parents", nargs="+", required=True)
    p.add_argument("--allow-growth", action="store_true")
    p = sub.add_parser("verify-pour")
    p.add_argument("--segment", required=True, help="segment filename (in arc/) or absolute path")
    p.add_argument("--source", required=True, help="hot file (relative to the store)")
    p.add_argument("--span", required=True, help="A:B — the 0-based half-open masked line range")
    p = sub.add_parser("lock")
    p.add_argument("session")
    p = sub.add_parser("unlock")
    p.add_argument("session")
    sub.add_parser("rebuild")
    p = sub.add_parser("restore")
    p.add_argument("segment")
    p = sub.add_parser("lint")
    p.add_argument("--plugin-root",
                   default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    p = sub.add_parser("barrier")
    p.add_argument("--session", default="", help="this session's short id — a virtual entry minted by another is EXPIRED")
    p.add_argument("--file", action="append", help="one read-list file (repeatable); default: the index's recall list")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("pool")
    p.add_argument("--session", required=True, help="this session's short id")
    p.add_argument("--title", default="", help="this session's chat title, for the pool's session: line")
    p.add_argument("--task", required=True, help="the session's one-line derivation of its first prompt")
    p.add_argument("--now", required=True, help="the clock, YYYY-MM-DD HH:MM, copied from the hook stream")
    p.add_argument("--file", action="append", help="one read-list file (repeatable); default: the index's recall list")
    p.add_argument("--cap", type=int, default=POOL_CAP, help="the pool's cap in characters")
    p.add_argument("--reserve", type=int, default=POOL_RESERVE, help="room left for the judged pass's steering lines")
    p.add_argument("--out", default="", help="write the skeleton (or, with --picks, the pool) here as well")
    p.add_argument("--picks", default="", help="the child readers' picks file: `<file>:<line> || bears: <clause>` "
                                              "lines under a `picks — <file>` head, or `picks (pass) — <file>` for "
                                              "the operator's own picks; each picked entry moves to steering with "
                                              "its clause, and the read: line credits each file to its head")
    p = sub.add_parser("standing")
    p.add_argument("--session", default="", help="this session's short id, for the barrier's expiry of virtual entries")
    p.add_argument("--part", type=int, default=0, help="which part to print when the rules outgrow one hook output")
    p.add_argument("--budget", type=int, default=STANDING_BUDGET, help="one part's size in characters")
    p = sub.add_parser("trace")
    p.add_argument("--session", default="", help="this session's short id, for the barrier's expiry of virtual entries")
    p.add_argument("--json", action="store_true")
    p.add_argument("--dry", action="store_true", help="report without recording the heads")
    args, extra = ap.parse_known_args()
    if args.cmd != "mask" and extra:
        ap.error(f"unrecognized arguments: {' '.join(extra)}")
    if args.cmd == "check":
        sys.exit(cmd_check(args.store))
    if args.cmd == "mask":
        print("phi.py mask: retired — naming what is cold is the sweep moment's judgment, by head line "
              "(hooks/operator-prompt.md); nothing scores entries on a grid", file=sys.stderr)
        sys.exit(2)
    if args.cmd == "verify-merge":
        sys.exit(cmd_verify_merge(args))
    if args.cmd == "verify-pour":
        sys.exit(cmd_verify_pour(args, args.store))
    if args.cmd == "lock":
        sys.exit(cmd_lock(args, args.store))
    if args.cmd == "unlock":
        sys.exit(cmd_lock(args, args.store, release=True))
    if args.cmd == "rebuild":
        sys.exit(cmd_rebuild(args.store))
    if args.cmd == "restore":
        sys.exit(cmd_restore(args))
    if args.cmd == "lint":
        sys.exit(cmd_lint(args.plugin_root))
    if args.cmd == "barrier":
        sys.exit(cmd_barrier(args, args.store))
    if args.cmd == "pool":
        sys.exit(cmd_pool(args, args.store))
    if args.cmd == "standing":
        sys.exit(cmd_standing(args, args.store))
    if args.cmd == "trace":
        sys.exit(cmd_trace(args, args.store))
    ap.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
