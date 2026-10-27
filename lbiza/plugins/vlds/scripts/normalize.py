#!/usr/bin/env python3
"""normalize.py — the φ-register's mechanical normalize sweep: the light classes at every turn's close, run
through phi.py's gates at every step.

Run, from anywhere:
  python normalize.py --store <store> --session <id> --light --dry   plan the light sweep, print it, write nothing
  python normalize.py --store <store> --session <id> --light         run it: lock, write, verify, trim, attach,
                                                                     log, index, unlock, check
  python normalize.py --store <store> --session <id> --pour ledger.md:36,42 --pour data-store.md:41 [--dry]
                                                                     a judged pour: the operator's sweep moment
                                                                     scores which entries are cold and names them
                                                                     by head line; this places them — one child at
                                                                     the one position the count opens, byte-checked
                                                                     — or says which counts near it would open one
  python normalize.py --store <store> --session <id> --move <record>:<position> [--dry]
                                                                     relocate one attached dispatch record to the
                                                                     live segment at <position> — the one move the
                                                                     light attacher cannot make, since it only
                                                                     places records still unregistered; byte-checked
                                                                     at the target, the source's overflow reported;
                                                                     on the owner's word, never a hand edit
  python normalize.py --store <store> --session <id> --detach <record> [--dry]
                                                                     unregister one attached dispatch record from the
                                                                     live segment that holds it — the record stays in
                                                                     arc/, owed registration again, and a later attach
                                                                     or move gives it a home; with --move, the swap
                                                                     that clears a position's overflow; on the word
The Stop hook (hooks/vlds_hooks.py turn-close) runs the --light form after every reply and hands the one-line
report to the next prompt hook, which prints it — the operation is announced by the closing that precedes it and
reported by the prompt that follows it. The --pour form is the judged sweep's mechanics: judgment names the
entries, arithmetic places them, and the gates verify every step, so no model writes a segment by hand.

What is light — the cold classes decided by rule alone, no judgment:
  attach   a hook-poured dispatch record (arc/dispatch-<stamp>-<session>.md) still unregistered is attached to the
           highest-position live segment with room for it (its bytes count toward the segment's capacity, exactly
           as phi.py check counts them); a record no segment can hold stays owed, and the report says so
  expire   a virtual.md entry minted by another session is past its turn by definition: its disposition is set to
           expired and the entry poured
  logger   when logger.md holds more live entries than its budget, its oldest pour down to the low-water mark
           (three quarters of the budget), so the sweep's own log line does not re-open the debt it just settled
Everything else — which local-storage ruling is spent, which data-store claim is stale, which ledger correction's
lesson is doctrine by now — is scored, not counted, and stays the judged sweep's: the store's own sweep frag.

Placement is the counter's, never a choice: the pour total N after the sweep must read Zeckendorf(N) on the
register, so the positions that leave the register are the child's parents and the one position that joins it is
the child. The light planner accepts a pour count only when exactly ONE position joins — one child, byte-checked
against its capacity with attachments included — because a count that opens two positions needs a judged split; it
tries the target count first, then smaller counts down to one, then larger ones. It runs only on a clean register
('2' and '11' debt are the judged sweep's) and refuses when the register does not read Zeckendorf of its own pour
sum. Attachments need no counter and run either way.

The run, in the frag's own order: phi.py lock — the expiry rewrite in the hot file — write the child — verify-merge
(every parent entry verbatim in the child) — verify-pour (every poured block verbatim in the child) — stamp the child
`verified:` (the commit point) — delete parents — trim the hot spans — attach — one logger entry when anything moved
— rewrite phi-index.md — unlock — check. A failed gate stops the run where it stands: what was verified stays, what
was not is never deleted, and the report names the step — debt, never corruption.
"""

import argparse
import datetime
import hashlib
import os
import re
import subprocess
import sys

CACHE = [1, 2]
while len(CACHE) < 40:
    CACHE.append(CACHE[-1] + CACHE[-2])

DEFAULT_BUDGET = {"local-storage.md": 21, "index.md": 21, "data-store.md": 34, "ledger.md": 21,
                  "tombstones.md": 21, "virtual.md": 13, "session-storage.md": 13, "logger.md": 34,
                  "briefs.md": 21}
HOT_ORDER = ["local-storage.md", "index.md", "data-store.md", "ledger.md", "tombstones.md", "virtual.md",
             "session-storage.md", "logger.md", "briefs.md", "dispatch.md"]
ID_PREFIX = {"data-store.md": "ds", "ledger.md": "le", "logger.md": "lg", "virtual.md": "vr",
             "local-storage.md": "ls", "session-storage.md": "ss", "tombstones.md": "ts", "index.md": "ix",
             "briefs.md": "br"}
SEG_NAME_RE = re.compile(r"^arc-(\d+)-([a-z]+)\.md$")
SEG_TOKEN_RE = re.compile(r"\barc-(\d+)-([a-z]+)\b")
POURED_DISPATCH_RE = re.compile(r"^dispatch-\d{8}-\d{6}-[0-9A-Za-z-]{1,12}\.md$")
STAMP_RE = re.compile(r"\b(20\d\d-\d\d-\d\d(?: \d\d:\d\d)?)\b")
TIME_FIELD_RE = re.compile(r"^  time:\s*(20\d\d-\d\d-\d\d(?: \d\d:\d\d)?)", re.M)
MINTED_RE = re.compile(r"^  minted:\s*session\s+([0-9A-Za-z-]+)", re.M)
DISPOSITION_RE = re.compile(r"^  disposition:\s*pending\s*$")
LOW_WATER = 0.75            # the logger pours down to this fraction of its budget
NOW_FMT = "%Y-%m-%d %H:%M"
PHI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phi.py")


# ─── files ──────────────────────────────────────────────────────────────────────────────────────────────

def read(p):
    with open(p, encoding="utf-8", newline="") as f:
        return f.read()


def write(p, text):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def phi(store, *args):
    r = subprocess.run([sys.executable, PHI, "--store", store, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


class Hot:
    """A hot file parsed on LF: its lines, the header separator's index, the entry blocks as half-open line ranges
    (a column-0 '- ' line plus its two-space continuation lines), and the newline it was written with."""

    def __init__(self, path):
        self.path = path
        raw = read(path)
        self.crlf = "\r\n" in raw
        self.lines = raw.replace("\r\n", "\n").split("\n")
        try:
            self.sep = self.lines.index("---")
        except ValueError:
            self.sep = -1
        self.blocks = []
        i = self.sep + 1
        while i < len(self.lines):
            if self.lines[i].startswith("- "):
                j = i + 1
                while j < len(self.lines) and self.lines[j].startswith("  "):
                    j += 1
                self.blocks.append((i, j))
                i = j
            else:
                i += 1

    def text(self, blk):
        return "\n".join(self.lines[blk[0]:blk[1]])

    def save(self, drop=()):
        drop = set(drop)
        text = "\n".join(l for i, l in enumerate(self.lines) if i not in drop)
        write(self.path, text.replace("\n", "\r\n") if self.crlf else text)


def entry_stamp(text):
    """The entry's own time — its `time:` field when it has one, else the first stamp in it (a logger head line)."""
    m = TIME_FIELD_RE.search(text) or STAMP_RE.search(text)
    return m.group(1) if m else ""


def expired_line(now):
    """The disposition a virtual entry gets when another session's turn close pours it — written to the hot file
    first and poured verbatim, so the archive says why the entry left."""
    return f"  disposition: expired (turn close {now}; minted by another session, its turn over)"


def span_label(fname, stamps):
    stamps = [s for s in stamps if s]
    base = fname[:-3]
    if not stamps:
        return base
    return f"{base} {stamps[0]}" if stamps[0] == stamps[-1] else f"{base} {stamps[0]} .. {stamps[-1]}"


# ─── segments ───────────────────────────────────────────────────────────────────────────────────────────

def parse_segment(path):
    """(header dict, [verbatim entry blocks]) — a ```yaml-fenced header, then entries between column-0 '---'."""
    lines = read(path).replace("\r\n", "\n").split("\n")
    first = next(i for i, l in enumerate(lines) if l.strip())
    if lines[first] != "```yaml":
        raise ValueError(f"{os.path.basename(path)}: header is not a ```yaml fence")
    close = next(i for i in range(first + 1, len(lines)) if lines[i] == "```")
    header = {}
    for l in lines[first + 1:close]:
        m = re.match(r"^([A-Za-z-]+):\s*(.*)$", l)
        if m:
            header[m.group(1)] = m.group(2)
    entries, cur = [], []
    for l in lines[close + 1:]:
        if l == "---":
            if cur and any(x.strip() for x in cur):
                entries.append("\n".join(cur).strip("\n"))
            cur = []
        else:
            cur.append(l)
    if cur and any(x.strip() for x in cur):
        entries.append("\n".join(cur).strip("\n"))
    return header, entries


def segment_text(name, position, entries, extra):
    head = [f"segment: {name[:-3]}", f"position: {position}", f"weight-kb: {CACHE[position - 1]}",
            f"seq: {name[:-3].rsplit('-', 1)[1]}"]
    if extra.get("verified"):
        head.append(f"verified: {extra['verified']}")
    head += [f"pours: {extra['pours']}", f"entries: {len(entries)}", f"spans: {extra['spans']}",
             f"poured-from: {extra['poured-from']}"]
    for k in ("merged-from", "settled", "attached"):
        if extra.get(k):
            head.append(f"{k}: {extra[k]}")
    body = "".join(f"---\n{eid}\n\n{b}\n" for eid, b in entries)
    return "```yaml\n" + "\n".join(head) + "\n```\n" + body, body


def stamp_verified(path, name, position, entries, extra, now):
    _t, body = segment_text(name, position, entries, extra)
    extra = dict(extra, verified=f"{now} sha={hashlib.sha256(body.encode('utf-8')).hexdigest()[:12]}")
    text, _b = segment_text(name, position, entries, extra)
    write(path, text)
    return extra["verified"]


def attach_to_segment(path, names):
    """Register `names` under an existing segment's `attached:` header line — a header edit; the `verified:` sha
    covers the body, so it stands."""
    text = read(path)
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    first = next(i for i, l in enumerate(lines) if l.strip())
    close = next(i for i in range(first + 1, len(lines)) if lines[i] == "```")
    for i in range(first + 1, close):
        if lines[i].startswith("attached:"):
            have = [a.strip() for a in lines[i][len("attached:"):].split(",") if a.strip()]
            lines[i] = "attached: " + ", ".join(have + [n for n in names if n not in have])
            break
    else:
        lines.insert(close, "attached: " + ", ".join(names))
    write(path, nl.join(lines))


def detach_from_segment(path, name):
    """Drop `name` from an existing segment's `attached:` header line — a header edit, like attach_to_segment,
    the `verified:` sha covering the body untouched; the line goes when nothing is left on it. True when the
    name was there."""
    text = read(path)
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    first = next(i for i, l in enumerate(lines) if l.strip())
    close = next(i for i in range(first + 1, len(lines)) if lines[i] == "```")
    for i in range(first + 1, close):
        if lines[i].startswith("attached:"):
            have = [a.strip() for a in lines[i][len("attached:"):].split(",") if a.strip()]
            if name not in have:
                return False
            have.remove(name)
            if have:
                lines[i] = "attached: " + ", ".join(have)
            else:
                del lines[i]
            write(path, nl.join(lines))
            return True
    return False


def attached_list(header):
    return [a.strip() for a in header.get("attached", "").split(",") if a.strip()]


def live_segments(arc):
    """{name: {position, header, entries, bytes, attached_bytes}} for every arc-<p>-<seq>.md in arc/."""
    out = {}
    if not os.path.isdir(arc):
        return out
    for f in sorted(os.listdir(arc)):
        m = SEG_NAME_RE.match(f)
        if not m:
            continue
        header, entries = parse_segment(os.path.join(arc, f))
        att = sum(os.path.getsize(os.path.join(arc, a)) for a in attached_list(header)
                  if os.path.exists(os.path.join(arc, a)))
        out[f] = {"position": int(m.group(1)), "header": header, "entries": entries,
                  "bytes": os.path.getsize(os.path.join(arc, f)), "attached_bytes": att}
    return out


def next_seq(arc, position, segments):
    """The next letter at a position — after every letter ever used there: live names and every arc-<p>-<x> token
    in a live header (merged-from, poured-from), so a name retired inside a merge is never reused."""
    used = set()
    for name, seg in segments.items():
        for text in [name] + list(seg["header"].values()):
            for m in SEG_TOKEN_RE.finditer(text):
                if int(m.group(1)) == position:
                    used.add(m.group(2))
    if not used:
        return "a"
    return chr(ord(max(used, key=lambda s: (len(s), s))[-1]) + 1)


def max_ids(segments):
    top = {}
    for seg in segments.values():
        for e in seg["entries"]:
            m = re.match(r"^id: ([a-z]{2})-(\d{4})", e)
            if m:
                top[m.group(1)] = max(top.get(m.group(1), 0), int(m.group(2)))
    return top


def zeckendorf(n):
    out = []
    for p in range(len(CACHE), 0, -1):
        if CACHE[p - 1] <= n:
            out.append(p)
            n -= CACHE[p - 1]
    return out


def register_string(positions):
    top = max(positions)
    return "".join("1" if p in positions else "0" for p in range(top, 0, -1))


# ─── the index ──────────────────────────────────────────────────────────────────────────────────────────

def parse_index(store):
    path = os.path.join(store, "phi-index.md")
    if not os.path.exists(path):
        return None, None
    text = read(path)
    section, rows = None, {"positions": [], "hot": [], "epochs": []}
    for l in text.replace("\r\n", "\n").split("\n"):
        if l.startswith("## "):
            section = l[3:].strip()
            continue
        if not l.startswith("|") or set(l.replace("|", "").strip()) <= {"-", " ", ":"}:
            continue
        cells = [c.strip() for c in l.strip("|").split("|")]
        if section in rows and cells[0] not in ("pos", "file"):
            rows[section].append(cells)
    return text, rows


def hot_count(store, fname):
    path = os.path.join(store, fname)
    ls = read(path).replace("\r\n", "\n").split("\n")
    try:
        start = ls.index("---") + 1
    except ValueError:
        start = 0
    return sum(1 for l in ls[start:] if l.startswith("- "))


def write_index(store, session8, now, plan, children_written, attached_now, old_text, old_rows, reg, total,
                via="the turn-close light sweep (scripts/normalize.py --light)"):
    """Rewrite phi-index.md from the state on disk: positions (the child's row computed, an untouched row kept
    with its attached column refreshed), hot (recounted; at-sweep moves for the poured files), recall (kept
    verbatim — a user's edit is a ruling), epochs (k+1 for each poured file), updated."""
    arc = os.path.join(store, "arc")
    old_pos = {r[2]: r for r in old_rows["positions"]}
    old_hot = {r[0]: r for r in old_rows["hot"]}
    old_k = {}
    for r in old_rows["epochs"]:
        try:
            old_k[r[0]] = int(r[1])
        except (ValueError, IndexError):
            pass
    pos_rows = {}
    for name, seg in live_segments(arc).items():
        p, h = seg["position"], seg["header"]
        if name in children_written or name not in old_pos:
            pos_rows[p] = (f"| {p} | {CACHE[p - 1]} | {name} | {seg['bytes']} | {h.get('pours', '')} | "
                           f"{h.get('spans', '')} | {h.get('attached') or '—'} |")
        else:
            r = list(old_pos[name])
            while len(r) < 7:
                r.append("—")
            r[3] = str(seg["bytes"])
            r[6] = h.get("attached") or "—"
            pos_rows[p] = "| " + " | ".join(r) + " |"
    hot_rows = []
    for fname in HOT_ORDER:
        path = os.path.join(store, fname)
        if not os.path.exists(path):
            continue
        live = hot_count(store, fname)
        old = old_hot.get(fname)
        at = live if fname in plan["pours"] else (old[2] if old and len(old) > 2 else str(live))
        budget = old[4] if old and len(old) > 4 else str(DEFAULT_BUDGET.get(fname, "floor"))
        hot_rows.append(f"| {fname} | {live} | {at} | {os.path.getsize(path)} | {budget} | — | ok |")
    epochs = dict(old_k)
    for fname in plan["pours"]:
        epochs[fname] = epochs.get(fname, 0) + 1
    text = old_text.replace("\r\n", "\n")
    head = text[:text.index("register:")] if "register:" in text else text.split("\n## ", 1)[0] + "\n\n"
    recall = ""
    if "## recall" in text:
        tail = text[text.index("## recall"):]
        recall = (tail[:tail.index("\n## ")] if "\n## " in tail else tail.split("\n\nupdated:")[0]).rstrip("\n")
    detail = "; ".join(f"{n} <- {', '.join(plan['child']['parents']) or 'no parent'} + "
                       f"{', '.join(plan['pours'])}" for n in children_written)
    if attached_now:
        detail += ("; " if detail else "") + "; ".join(f"attached {', '.join(v)} to {k}" for k, v in attached_now.items())
    n_pours = sum(len(v["blocks"]) for v in plan["pours"].values())
    index = (head + f"register: {reg}\n\n## positions\n\n| pos | weight-kb | segment | bytes | pours | span | attached |\n"
             "| --- | --- | --- | --- | --- | --- | --- |\n"
             + "\n".join(pos_rows[p] for p in sorted(pos_rows, reverse=True))
             + "\n\n## hot\n\n| file | live | at-sweep | bytes | budget | watermark | pressure |\n"
             "| --- | --- | --- | --- | --- | --- | --- |\n" + "\n".join(hot_rows)
             + ("\n\n" + recall if recall else "")
             + "\n\n## epochs\n\n| file | k | a | b |\n| --- | --- | --- | --- |\n"
             + "\n".join(f"| {f} | {k} | {CACHE[k]} | {CACHE[k + 1]} |" for f, k in epochs.items())
             + f"\n\nupdated: {now} by {session8} via {via} — "
             f"{n_pours} pours" + (f" ({pour_counts(plan)})" if n_pours else "")
             + (f"; {detail}" if detail else "") + f"; register {reg} = Zeckendorf({total}); every deletion "
             "script-verified; no watermark left open\n")
    write(os.path.join(store, "phi-index.md"), index)


# ─── the light plan ─────────────────────────────────────────────────────────────────────────────────────

def new_plan():
    return {"pours": {}, "child": None, "attach": {}, "owed": [], "notes": [], "total": 0, "register": ""}


def _register(store, plan):
    """The register as it stands — budgets, live segments, positions, the pour sum — or None when there is no
    index; '2'/'11' debt and counter drift go to plan["owed"] and leave `clean` False."""
    old_text, old_rows = parse_index(store)
    if old_text is None:
        plan["owed"].append("no phi-index.md — the register is not bootstrapped; nothing to place")
        return None
    budget = dict(DEFAULT_BUDGET)
    for r in old_rows["hot"]:
        try:
            budget[r[0]] = int(r[4])
        except (ValueError, IndexError):
            pass
    segments = live_segments(os.path.join(store, "arc"))
    positions = {}
    for name, seg in segments.items():
        positions.setdefault(seg["position"], []).append(name)
    occupied = sorted(positions, reverse=True)
    clean = all(len(v) == 1 for v in positions.values()) and \
        all(b != a - 1 for a, b in zip(occupied, occupied[1:]))
    sum_pours = sum(int(seg["header"].get("pours", 0) or 0) for seg in segments.values())
    if not clean:
        plan["owed"].append("register '2' or '11' debt — a RESOLVE or CARRY is the judged sweep's")
    elif occupied and zeckendorf(sum_pours) != occupied:
        plan["owed"].append(f"register {occupied} does not read Zeckendorf({sum_pours}) = {zeckendorf(sum_pours)} — "
                            "counter drift; the judged sweep reconciles it")
        clean = False
    return {"budget": budget, "segments": segments, "positions": positions, "occupied": occupied, "clean": clean,
            "sum_pours": sum_pours}


def plan_pours(store, session, now, spec):
    """A judged pour placed mechanically: `spec` names each hot file's entries by the 1-based line of their head
    (the operator's scoring), and this places them — one child at the one position the count opens, byte-checked
    — or says which counts near it would open exactly one position."""
    plan = new_plan()
    reg = _register(store, plan)
    if reg is None or not reg["clean"]:
        return plan
    segments, positions, occupied, sum_pours = reg["segments"], reg["positions"], reg["occupied"], reg["sum_pours"]
    hots, pours, k = {}, {}, 0
    for fname, lines1 in spec.items():
        path = os.path.join(store, fname)
        if fname not in ID_PREFIX or not os.path.exists(path):
            plan["owed"].append(f"{fname}: not a hot file that pours")
            return plan
        hf = Hot(path)
        hots[fname] = hf
        heads = {s + 1: (s, e) for s, e in hf.blocks}
        blocks = []
        for l1 in lines1:
            if l1 not in heads:
                plan["owed"].append(f"{fname}: line {l1} is not an entry head (heads at {sorted(heads)})")
                return plan
            blocks.append(heads[l1])
        pours[fname] = {"blocks": blocks, "cold": f"{len(blocks)} entries the sweep moment scored cold (head lines "
                                                 f"{', '.join(str(l) for l in lines1)})"}
        k += len(blocks)
    if not k:
        plan["owed"].append("no pours named")
        return plan
    total = sum_pours + k
    target = zeckendorf(total)
    new = [p for p in target if p not in occupied]
    gone = [p for p in occupied if p not in target]
    if len(new) != 1:
        alts = [kk for kk in range(max(1, k - 3), k + 9)
                if len([p for p in zeckendorf(sum_pours + kk) if p not in occupied]) == 1]
        plan["owed"].append(f"{k} pours would open {len(new)} positions {new} — counts that open exactly one: "
                            f"{alts}; name that many entries")
        return plan
    child = build_child(store, segments, new[0], [positions[p][0] for p in gone], pours, hots,
                        {"virtual.md": {}}, now, total, target)
    if child["size"] > child["cap"]:
        plan["owed"].append(f"{child['name']} would hold {child['size']:,} B of {child['cap']:,} — over capacity; "
                            "fewer or smaller entries")
        return plan
    plan["pours"], plan["child"], plan["total"], plan["register"] = pours, child, total, register_string(target)
    _attach(store, plan, segments)
    return plan


def plan_light(store, session, now):
    """The light classes as a plan: which hot blocks pour, into which child at which position with which parents,
    which records attach where — or what stays owed and why."""
    session8 = session[:8]
    arc = os.path.join(store, "arc")
    plan = new_plan()
    reg = _register(store, plan)
    if reg is None:
        return plan
    budget, segments, positions, occupied, clean, sum_pours = (
        reg["budget"], reg["segments"], reg["positions"], reg["occupied"], reg["clean"], reg["sum_pours"])

    # the cold candidates
    hots = {}
    virtual_blocks, expire_lines = [], {"virtual.md": {}}   # {file: {line index: the rewritten line}}
    vpath = os.path.join(store, "virtual.md")
    if os.path.exists(vpath):
        hv = Hot(vpath)
        hots["virtual.md"] = hv
        for blk in hv.blocks:
            t = hv.text(blk)
            m = MINTED_RE.search(t)
            if m and m.group(1)[:8] != session8:
                virtual_blocks.append(blk)
                for i in range(blk[0], blk[1]):
                    if DISPOSITION_RE.match(hv.lines[i]):
                        expire_lines["virtual.md"][i] = expired_line(now)
    logger_blocks, k_target, l_live = [], 0, 0
    lpath = os.path.join(store, "logger.md")
    if os.path.exists(lpath):
        hl = Hot(lpath)
        hots["logger.md"] = hl
        l_live = len(hl.blocks)
        if l_live > budget.get("logger.md", 34):
            k_target = l_live - int(budget["logger.md"] * LOW_WATER)
            logger_blocks = hl.blocks

    # the count search — one child, byte-checked
    if clean and (virtual_blocks or k_target):
        kl_order = list(range(k_target, 0, -1)) + list(range(k_target + 1, l_live)) if k_target else [0]
        kv_order = [len(virtual_blocks)] + ([0] if virtual_blocks else [])
        found = None
        for kv in kv_order:
            for kl in kl_order:
                if kv + kl == 0:
                    continue
                total = sum_pours + kv + kl
                target = zeckendorf(total)
                new = [p for p in target if p not in occupied]
                gone = [p for p in occupied if p not in target]
                if len(new) != 1:
                    continue
                cpos = new[0]
                parents = [positions[p][0] for p in gone]
                pours = {}
                if kv:
                    pours["virtual.md"] = {"blocks": virtual_blocks[:kv], "cold": "entries minted by another session — "
                                           "past their turn, expired at turn close"}
                if kl:
                    pours["logger.md"] = {"blocks": logger_blocks[:kl], "cold": f"the {kl} oldest entries, the logger past "
                                          f"its budget of {budget['logger.md']} ({l_live} live)"}
                child = build_child(store, segments, cpos, parents, pours, hots, expire_lines, now, total, target)
                if child["size"] <= child["cap"]:
                    found = (pours, child, total, target)
                    break
            if found:
                break
        if found:
            pours, child, total, target = found
            plan["pours"], plan["child"], plan["total"] = pours, child, total
            plan["register"] = register_string(target)
        else:
            what = []
            if virtual_blocks:
                what.append(f"{len(virtual_blocks)} expired virtual entr{'y' if len(virtual_blocks) == 1 else 'ies'}")
            if k_target:
                what.append(f"logger.md {l_live} over budget {budget['logger.md']}")
            plan["owed"].append(f"{' and '.join(what)}: no pour count from this register opens exactly one position "
                                "with the room — the judged sweep places it")
    if not plan["child"]:
        plan["total"] = sum_pours
        plan["register"] = register_string(occupied) if occupied else ""
    _attach(store, plan, segments)
    return plan


def _attach(store, plan, segments):
    """Attachments — against the final segment set: the untouched segments and the planned child."""
    arc = os.path.join(store, "arc")
    final = {}
    for name, seg in segments.items():
        if plan["child"] and name in plan["child"]["parents"]:
            continue
        final[name] = {"position": seg["position"], "size": seg["bytes"] + seg["attached_bytes"],
                       "attached": attached_list(seg["header"])}
    if plan["child"]:
        c = plan["child"]
        final[c["name"]] = {"position": c["position"], "size": c["size"], "attached": list(c["attached"])}
    registered = {a for f in final.values() for a in f["attached"]}
    records = [f for f in sorted(os.listdir(arc)) if POURED_DISPATCH_RE.match(f) and f not in registered] \
        if os.path.isdir(arc) else []
    for rec in records:
        size = os.path.getsize(os.path.join(arc, rec))
        home = None
        for name in sorted(final, key=lambda n: -final[n]["position"]):
            cap = CACHE[final[name]["position"] - 1] * 1024
            if final[name]["size"] + size <= cap:
                home = name
                break
        if home is None:
            plan["owed"].append(f"arc/{rec} ({size:,} B): no live segment has the room — attachment owed to a "
                                "count that opens one")
            continue
        final[home]["size"] += size
        final[home]["attached"].append(rec)
        plan["attach"].setdefault(home, []).append(rec)
        if plan["child"] and home == plan["child"]["name"]:
            plan["child"]["attached"].append(rec)
            plan["child"]["size"] += size
    if plan["child"]:
        plan["child"]["extra"]["attached"] = ", ".join(plan["child"]["attached"])   # the header names them
    return plan


def build_child(store, segments, cpos, parents, pours, hots, expire_lines, now, total, target):
    arc = os.path.join(store, "arc")
    ids = max_ids(segments)
    entries, spans, poured_from, attached, n = [], [], [], [], 0
    for parent in parents:
        h, es = segments[parent]["header"], segments[parent]["entries"]
        for e in es:
            first, _nl, rest = e.partition("\n")
            entries.append((first, rest.lstrip("\n")))
        if h.get("spans"):
            spans.append(h["spans"])
        poured_from.append(f"{parent} ({h.get('poured-from', '')})")
        attached += [a for a in attached_list(h) if a not in attached]
        n += int(h.get("pours", 0) or 0)
    for fname, spec in pours.items():
        hf = hots[fname]
        prefix = ID_PREFIX[fname]
        stamps = []
        rewritten = expire_lines.get(fname, {})
        for blk in spec["blocks"]:
            ids[prefix] = ids.get(prefix, 0) + 1
            lines = [rewritten.get(i, hf.lines[i]) for i in range(blk[0], blk[1])]
            entries.append((f"id: {prefix}-{ids[prefix]:04d}", "\n".join(lines)))
            stamps.append(entry_stamp("\n".join(lines)))
        spans.append(span_label(fname, stamps))
        poured_from.append(f"{fname} ({spec['cold']})")
        n += len(spec["blocks"])
    reg = register_string(target)
    name = f"arc-{cpos}-{next_seq(arc, cpos, segments)}.md"
    extra = {"pours": n, "spans": "; ".join(spans), "poured-from": "; ".join(poured_from),
             "merged-from": ", ".join(parents), "attached": ", ".join(attached),
             "settled": f"computed cascade, turn-close light sweep {now} — direct placement; audit = the counter "
                        f"invariant (register {reg} = Zeckendorf({total}))"}
    # sized WITH the `verified:` line the stamp adds later — a position-1 segment has no margin for it
    probe = dict(extra, verified=f"{now} sha={'0' * 12}")
    text, _b = segment_text(name, cpos, entries, probe)
    size = len(text.encode("utf-8")) + sum(os.path.getsize(os.path.join(arc, a)) for a in attached
                                           if os.path.exists(os.path.join(arc, a)))
    return {"position": cpos, "name": name, "parents": parents, "entries": entries, "extra": extra,
            "attached": attached, "size": size, "cap": CACHE[cpos - 1] * 1024}


def pour_counts(plan):
    """'1 virtual.md, 12 logger.md' — the pours per file, for every report line."""
    return ", ".join(f"{len(v['blocks'])} {f}" for f, v in plan["pours"].items())


def describe(plan):
    lines = []
    for fname, spec in plan["pours"].items():
        lines.append(f"pour {len(spec['blocks'])} of {fname} — {spec['cold']}")
    if plan["child"]:
        c = plan["child"]
        lines.append(f"child {c['name']} at position {c['position']} <- parents {c['parents'] or 'none'} + "
                     f"{list(plan['pours'])}, {c['size']:,} B of {c['cap']:,}; register {plan['register']} = "
                     f"Zeckendorf({plan['total']})")
    for seg, recs in plan["attach"].items():
        lines.append(f"attach {', '.join(recs)} -> {seg}")
    for o in plan["owed"]:
        lines.append(f"owed: {o}")
    return lines


# ─── the run ────────────────────────────────────────────────────────────────────────────────────────────

def run_light(store, session, now, dry, spec=None):
    """The run — `spec` None: the light classes (the Stop hook's turn-close); `spec` given: the judged pours it
    names, placed mechanically (the operator's sweep moment). The report line's prefix names which."""
    session8 = session[:8]
    arc = os.path.join(store, "arc")
    tag = "sweep" if spec else "turn-close"
    via = ("the sweep moment, placed by scripts/normalize.py --pour" if spec
           else "the turn-close light sweep (scripts/normalize.py --light)")
    try:
        plan = plan_pours(store, session, now, spec) if spec else plan_light(store, session, now)
    except Exception as e:  # noqa: BLE001 — a plan that cannot be read is a report, not a traceback
        print(f"{tag}: stopped at plan — {type(e).__name__}: {e}")
        return 1
    for l in describe(plan):
        print(l)
    moves = bool(plan["child"] or plan["attach"])
    if not moves:
        owed = "; ".join(plan["owed"])
        report = f"{tag}: nothing to move{' — owed: ' + owed if owed else ''}"
        print(report)
        return 0 if not spec else 1
    if dry:
        print(f"{tag}: dry run — nothing written")
        return 0
    rc, out = phi(store, "lock", session)
    if rc != 0:
        report = f"{tag}: skipped — {out.splitlines()[-1] if out else 'lock refused'}"
        print(report)
        return 0
    step = "lock"
    written, attached_now = [], {}
    try:
        old_text, old_rows = parse_index(store)
        c = plan["child"]
        if c:
            step = "expiry rewrite"
            for fname, spec in plan["pours"].items():
                hf = hots_for(plan, store)[fname]
                if fname == "virtual.md":
                    changed = False
                    for blk in spec["blocks"]:
                        for i in range(blk[0], blk[1]):
                            if DISPOSITION_RE.match(hf.lines[i]):
                                hf.lines[i] = expired_line(now)
                                changed = True
                    if changed:
                        hf.save()
            step = "write child"
            path = os.path.join(arc, c["name"])
            if os.path.exists(path):
                raise RuntimeError(f"{c['name']} already exists")
            text, _b = segment_text(c["name"], c["position"], c["entries"], c["extra"])
            write(path, text)
            written.append(c["name"])
            if c["parents"]:
                step = "verify-merge"
                rc, out = phi(store, "verify-merge", "--child", path, "--parents",
                              *[os.path.join(arc, p) for p in c["parents"]], "--allow-growth")
                if rc != 0 or "PASS" not in out:
                    raise RuntimeError(out)
            step = "verify-pour"
            for fname, spec in plan["pours"].items():
                for s, e in spec["blocks"]:
                    rc, out = phi(store, "verify-pour", "--segment", c["name"], "--source", fname, "--span", f"{s}:{e}")
                    if rc != 0 or "PASS" not in out:
                        raise RuntimeError(f"{fname} {s}:{e}: {out}")
            step = "stamp verified"
            stamp_verified(path, c["name"], c["position"], c["entries"], c["extra"], now)
            step = "delete parents"
            for p in c["parents"]:
                os.remove(os.path.join(arc, p))
            step = "trim"
            for fname, spec in plan["pours"].items():
                hf = Hot(os.path.join(store, fname))
                drop = set()
                for s, e in spec["blocks"]:
                    drop.update(range(s, e))
                    if s > 0 and hf.lines[s - 1] == "":
                        drop.add(s - 1)
                hf.save(drop)
        step = "attach"
        for seg, recs in plan["attach"].items():
            if c and seg == c["name"]:
                attached_now[seg] = recs      # already in the child's header
                continue
            attach_to_segment(os.path.join(arc, seg), recs)
            attached_now[seg] = recs
        step = "logger entry"
        n_pours = sum(len(v["blocks"]) for v in plan["pours"].values())
        reg = plan["register"]
        parts = []
        if c:
            parts.append(f"{n_pours} pours ({pour_counts(plan)}) into {c['name']} <- "
                         f"{', '.join(c['parents']) or 'no parent'} ({c['size']:,} B of {c['cap']:,})")
        for seg, recs in attached_now.items():
            parts.append(f"attached {', '.join(recs)} to {seg}")
        if plan["owed"]:
            parts.append("still owed: " + "; ".join(plan["owed"]))
        headline = ("Judged sweep placed mechanically" if spec else "Turn-close light sweep")
        run_by = ("Scored by the operator's sweep moment, placed and run by scripts/normalize.py --pour." if spec
                  else "Run mechanically by scripts/normalize.py --light from the Stop hook.")
        entry = (f"\n- `[gc]` {now} — **{headline} — {n_pours} pours, register {reg}.** "
                 + "; ".join(parts) + f"; every deletion script-verified, no watermark left open. {run_by}\n")
        lpath = os.path.join(store, "logger.md")
        if os.path.exists(lpath):
            raw = read(lpath)
            write(lpath, raw + (entry.replace("\n", "\r\n") if "\r\n" in raw else entry))
        step = "index"
        write_index(store, session8, now, plan, written, attached_now, old_text, old_rows, reg, plan["total"], via)
    except Exception as e:  # noqa: BLE001 — the report names the step; nothing unverified was deleted
        print(f"{tag}: stopped at {step} — {type(e).__name__}: {e}")
        phi(store, "unlock", session)
        return 1
    rc, out = phi(store, "unlock", session)
    _rc, out = phi(store, "check")
    verdict = out.splitlines()[-1] if out else "check: no output"
    summary = []
    if c:
        summary.append(f"poured {n_pours} ({pour_counts(plan)}) into {c['name']}"
                       + (f" (merged {', '.join(c['parents'])})" if c["parents"] else ""))
    for seg, recs in attached_now.items():
        summary.append(f"attached {', '.join(recs)} to {seg}")
    if plan["owed"]:
        summary.append("owed: " + "; ".join(plan["owed"]))
    print(f"{tag}: {'; '.join(summary)}; register {reg}; {verdict}")
    return 0


def run_move(store, session, now, record, to_position, dry):
    """Relocate one attached dispatch record from the live segment that holds it to the live segment at
    `to_position` — the one move the light classes cannot make, since the attacher only places records still
    unregistered. Byte-checked at the target; the source's overflow reported cleared or not; the run through the
    lock, both headers, one logger entry, the index, the check. No entry is written, deleted, or rewritten: each
    body's `verified:` sha stands, because an attachment is a header line."""
    session8 = session[:8]
    arc = os.path.join(store, "arc")
    tag = "move"
    old_text, old_rows = parse_index(store)
    if old_text is None:
        print(f"{tag}: refused — no phi-index.md; the register is not bootstrapped")
        return 1
    segments = live_segments(arc)
    src = next((n for n, s in segments.items() if record in attached_list(s["header"])), None)
    if src is None:
        print(f"{tag}: refused — {record} is attached to no live segment (an unregistered record is the light "
              "sweep's to attach)")
        return 1
    rec_path = os.path.join(arc, record)
    if not os.path.exists(rec_path):
        print(f"{tag}: refused — arc/{record} is named by {src} but absent on disk")
        return 1
    dst = next((n for n, s in segments.items() if s["position"] == to_position), None)
    if dst is None:
        live = ", ".join(f"{n} (position {s['position']})"
                         for n, s in sorted(segments.items(), key=lambda kv: -kv[1]["position"]))
        print(f"{tag}: refused — no live segment at position {to_position}; live: {live or 'none'}")
        return 1
    if dst == src:
        print(f"{tag}: refused — {record} is already at position {to_position} ({src})")
        return 1
    size = os.path.getsize(rec_path)
    s_seg, d_seg = segments[src], segments[dst]
    s_cap, d_cap = CACHE[s_seg["position"] - 1] * 1024, CACHE[to_position - 1] * 1024
    s_before, d_before = s_seg["bytes"] + s_seg["attached_bytes"], d_seg["bytes"] + d_seg["attached_bytes"]
    s_after, d_after = s_before - size, d_before + size
    if d_after > d_cap:
        print(f"{tag}: refused — {dst} holds {d_before:,} B of {d_cap:,}; {record} ({size:,} B) needs "
              f"{d_after - d_cap:,} B more room than position {to_position} has")
        return 1
    cleared = ", overflow cleared" if s_before > s_cap >= s_after else ""
    print(f"{tag}: {record} ({size:,} B) from {src} (position {s_seg['position']}: {s_before:,} → {s_after:,} B "
          f"of {s_cap:,}{cleared}) to {dst} (position {to_position}: {d_before:,} → {d_after:,} B of {d_cap:,})")
    if dry:
        print(f"{tag}: dry run — nothing written")
        return 0
    rc, out = phi(store, "lock", session)
    if rc != 0:
        print(f"{tag}: skipped — {out.splitlines()[-1] if out else 'lock refused'}")
        return 0
    step = "lock"
    try:
        step = "detach"
        if not detach_from_segment(os.path.join(arc, src), record):
            raise RuntimeError(f"{record} not on {src}'s attached: line")
        step = "attach"
        attach_to_segment(os.path.join(arc, dst), [record])
        step = "register"
        plan = new_plan()
        reg = _register(store, plan)
        occupied = reg["occupied"] if reg else []
        reg_s = "".join("1" if p in occupied else "0" for p in range(max(occupied, default=0), 0, -1))
        total = reg["sum_pours"] if reg else 0
        step = "logger entry"
        entry = (f"\n- `[gc]` {now} — **Attachment moved — {record} from {src} to {dst}, register {reg_s}.** "
                 f"{src} (position {s_seg['position']}) {s_before:,} → {s_after:,} B of {s_cap:,}{cleared}; "
                 f"{dst} (position {to_position}) {d_before:,} → {d_after:,} B of {d_cap:,}; no entry written or "
                 "deleted, both bodies' verified: sha standing. Run mechanically by scripts/normalize.py --move "
                 "on the owner's word.\n")
        lpath = os.path.join(store, "logger.md")
        if os.path.exists(lpath):
            raw = read(lpath)
            write(lpath, raw + (entry.replace("\n", "\r\n") if "\r\n" in raw else entry))
        step = "index"
        write_index(store, session8, now, plan, [], {dst: [record]}, old_text, old_rows, reg_s, total,
                    via="an attachment move (scripts/normalize.py --move)")
    except Exception as e:  # noqa: BLE001 — the report names the step; a header edit is the only write before it
        print(f"{tag}: stopped at {step} — {type(e).__name__}: {e}")
        phi(store, "unlock", session)
        return 1
    phi(store, "unlock", session)
    _rc, out = phi(store, "check")
    verdict = out.splitlines()[-1] if out else "check: no output"
    print(f"{tag}: moved {record} ({size:,} B) from {src} to {dst}; {src} now {s_after:,} B of {s_cap:,}{cleared}; "
          f"{dst} now {d_after:,} B of {d_cap:,}; register {reg_s}; {verdict}")
    return 0


def run_detach(store, session, now, record, dry):
    """Unregister one attached dispatch record from the live segment that holds it — the record stays in arc/, owed
    registration again, for a later attach or move to home; with --move this is the swap that clears a position's
    overflow when the attacher filled the room first. The run through the lock, the header, one logger entry, the
    index, the check; no entry written, deleted, or rewritten."""
    session8 = session[:8]
    arc = os.path.join(store, "arc")
    tag = "detach"
    old_text, old_rows = parse_index(store)
    if old_text is None:
        print(f"{tag}: refused — no phi-index.md; the register is not bootstrapped")
        return 1
    segments = live_segments(arc)
    src = next((n for n, s in segments.items() if record in attached_list(s["header"])), None)
    if src is None:
        print(f"{tag}: refused — {record} is attached to no live segment")
        return 1
    rec_path = os.path.join(arc, record)
    size = os.path.getsize(rec_path) if os.path.exists(rec_path) else 0
    s_seg = segments[src]
    s_cap = CACHE[s_seg["position"] - 1] * 1024
    s_before = s_seg["bytes"] + s_seg["attached_bytes"]
    s_after = s_before - size
    print(f"{tag}: {record} ({size:,} B) off {src} (position {s_seg['position']}: {s_before:,} → {s_after:,} B "
          f"of {s_cap:,}); the record stays in arc/, unregistered")
    if dry:
        print(f"{tag}: dry run — nothing written")
        return 0
    rc, out = phi(store, "lock", session)
    if rc != 0:
        print(f"{tag}: skipped — {out.splitlines()[-1] if out else 'lock refused'}")
        return 0
    step = "lock"
    try:
        step = "detach"
        if not detach_from_segment(os.path.join(arc, src), record):
            raise RuntimeError(f"{record} not on {src}'s attached: line")
        step = "register"
        plan = new_plan()
        reg = _register(store, plan)
        occupied = reg["occupied"] if reg else []
        reg_s = "".join("1" if p in occupied else "0" for p in range(max(occupied, default=0), 0, -1))
        total = reg["sum_pours"] if reg else 0
        step = "logger entry"
        entry = (f"\n- `[gc]` {now} — **Attachment detached — {record} off {src}, register {reg_s}.** "
                 f"{src} (position {s_seg['position']}) {s_before:,} → {s_after:,} B of {s_cap:,}; the record stays "
                 "in arc/, owed registration again; no entry written or deleted, the body's verified: sha standing. "
                 "Run mechanically by scripts/normalize.py --detach on the owner's word.\n")
        lpath = os.path.join(store, "logger.md")
        if os.path.exists(lpath):
            raw = read(lpath)
            write(lpath, raw + (entry.replace("\n", "\r\n") if "\r\n" in raw else entry))
        step = "index"
        write_index(store, session8, now, plan, [], {}, old_text, old_rows, reg_s, total,
                    via="an attachment detached (scripts/normalize.py --detach)")
    except Exception as e:  # noqa: BLE001 — the report names the step; a header edit is the only write before it
        print(f"{tag}: stopped at {step} — {type(e).__name__}: {e}")
        phi(store, "unlock", session)
        return 1
    phi(store, "unlock", session)
    _rc, out = phi(store, "check")
    verdict = out.splitlines()[-1] if out else "check: no output"
    print(f"{tag}: detached {record} ({size:,} B) off {src}; {src} now {s_after:,} B of {s_cap:,}; register {reg_s}; "
          f"{verdict}")
    return 0


_HOTS = {}


def hots_for(plan, store):
    """The hot files the plan pours, parsed once per run (the planner's own parse is not kept)."""
    for fname in plan["pours"]:
        if fname not in _HOTS:
            _HOTS[fname] = Hot(os.path.join(store, fname))
    return _HOTS


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="normalize.py", description="VLDS φ-register mechanical normalize sweep")
    ap.add_argument("--store", default=os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", "p4", "vlds"))
    ap.add_argument("--session", required=True, help="the session id — the lock holder and the index's updated: line")
    ap.add_argument("--light", action="store_true", help="the light classes: attach, expire, logger overflow")
    ap.add_argument("--pour", action="append", default=[], metavar="FILE:L1,L2",
                    help="a judged pour: the hot file and the 1-based head lines of the entries scored cold; repeatable")
    ap.add_argument("--move", default=None, metavar="RECORD:POSITION",
                    help="relocate an attached dispatch record to the live segment at POSITION — the one move the "
                         "light attacher cannot make; on the owner's word")
    ap.add_argument("--detach", default=None, metavar="RECORD",
                    help="unregister an attached dispatch record from the live segment that holds it; with --move, "
                         "the swap that clears a position's overflow; on the owner's word")
    ap.add_argument("--dry", action="store_true", help="plan and print, write nothing")
    ap.add_argument("--now", default=None, help="the clock to stamp with (default: now)")
    args = ap.parse_args()
    idb_dir = os.path.join(os.path.abspath(args.store), "idb")
    if os.path.exists(os.path.join(idb_dir, "keys.tsv")) or (os.path.isdir(os.path.join(idb_dir, "runs")) and any(
            re.match(r"^[a-z][a-z-]*-\d{6,}\.md$", n) for n in os.listdir(os.path.join(idb_dir, "runs")))):
        print("normalize.py: refused — the store is on the keyspace; `idb.py light` is its turn-close pass and "
              "`idb.py pour` places a judged pour")
        return 1
    if args.detach:
        now = args.now or datetime.datetime.now().strftime(NOW_FMT)
        rc = run_detach(os.path.abspath(args.store), args.session, now, args.detach.strip(), args.dry)
        if rc != 0 or not args.move:
            return rc
    if args.move:
        record, _sep, pos = args.move.rpartition(":")
        if not record or not pos.strip().isdigit():
            ap.error(f"--move {args.move!r}: say <record>:<position>")
        now = args.now or datetime.datetime.now().strftime(NOW_FMT)
        return run_move(os.path.abspath(args.store), args.session, now, record.strip(), int(pos), args.dry)
    spec = None
    if args.pour:
        spec = {}
        for item in args.pour:
            fname, _sep, lines = item.partition(":")
            try:
                spec.setdefault(fname.strip(), []).extend(int(x) for x in lines.split(",") if x.strip())
            except ValueError:
                ap.error(f"--pour {item!r}: head lines must be integers")
    elif not args.light:
        ap.error("say --light (the mechanical classes), --pour FILE:LINES (a judged pour, placed here), "
                 "--move RECORD:POSITION (an attachment relocated), or --detach RECORD (an attachment unregistered)")
    now = args.now or datetime.datetime.now().strftime(NOW_FMT)
    return run_light(os.path.abspath(args.store), args.session, now, args.dry, spec)


if __name__ == "__main__":
    sys.exit(main())
