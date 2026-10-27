#!/usr/bin/env python3
"""record.py — the turn's close, mechanical: apply a record document to the store and print the derivation.

Run, from anywhere:
  python record.py --store <store> --session <id> --now "YYYY-MM-DD HH:MM" --record <path> [--dry]
  python record.py --store <store> --session <id> --now "YYYY-MM-DD HH:MM" - < record.md        (stdin)

The judgment of a close — what was addressed, which ruling the user made and in what words, which claim was
verified, which task moved — is the session's, composed once as the record; the labor of a close — appending each
entry in its file's shape, completing the dispatch rows, running the check — needs no judgment, so it runs here
in milliseconds and no model reads or writes the store for it. The derivation this prints is what the session
acts on and reports: what was written, what was updated, what was refused and why, the check's verdict, what is
owed. The operator subagent keeps the moments that need judgment: the barrier when a row resembles the message,
the intent of an unknown short message, the pool, the scoring of a sweep.

The record document: a `## <file>` line names a store file, and every block under it is an entry in that file's
own header shape — a column-0 `- field: value` head line and two-space continuation lines. One rule places it:
UPSERT BY HEAD. When an existing entry's head line begins with the block's head line, the block updates that entry
— each field it carries replaces the entry's line of that name, or is inserted after the entry's last line when
the entry has no such line; when no entry's head begins with it, the block is appended as a new entry. A dispatch
row is completed by giving its fingerprint's opening as the head and the fields to add; a task's state moves by
giving its `- task:` head and the new `state:` line; a ruling is appended by giving its whole shape. A head that
begins two entries is refused as ambiguous. Anything before the first `## ` line is ignored, so a record may open
with a title or a note.

What is refused, block by block, and reported rather than written: a file that is not a store file; a field the
file's header shape does not declare; a logger line that is not the tagged bullet the logger's header declares; a
`time:` that is a placeholder or later than --now by more than a minute (the same rules the pre-write gate
applies to a model's write, which cannot see inside a record file). A refusal never stops the other blocks.

Times: every `time:` in the record is the session's to write — copied from the hook stream's `now:`, or from the
message the entry belongs to; this script checks them and never invents one.
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PLUGIN, "hooks"))
try:
    from vlds_hooks import placeholder_times, future_times, NOW_FMT    # noqa: E402 — the gate's own time rules
except Exception:  # noqa: BLE001 — the hooks file is beside this one; without it the time scans are skipped
    placeholder_times = future_times = None
    NOW_FMT = "%Y-%m-%d %H:%M"

import datetime  # noqa: E402

sys.path.insert(0, HERE)
import partition as pt  # noqa: E402 — the p4 layout: a new session store starts with none of the shared files


def seed_from_peer(store, fname):
    """A file a new session store lacks, created from another session's copy of it — its header, up to and including
    the first `---` line, entries none: the file's shape is its header, and the header is the same in every session.
    A session-local file (virtual.md, session-storage.md) is read from this store alone, so its header comes from
    any other session's copy under the layout. Nothing is created when no session holds the file, or outside the
    p4 layout."""
    if not pt.partitioned(store):
        return False
    base = os.path.basename(fname)
    peers = pt.session_stores(store) if base in pt.SESSION_LOCAL else [peer for peer, _lb in pt.expand(store, fname)]
    for peer in peers:
        src = os.path.join(peer, fname)
        if os.path.normcase(os.path.abspath(peer)) == os.path.normcase(os.path.abspath(store)) or not os.path.exists(src):
            continue
        with open(src, encoding="utf-8") as f:
            lines = f.read().replace("\r\n", "\n").split("\n")
        if "---" not in lines:
            continue
        os.makedirs(store, exist_ok=True)
        with open(os.path.join(store, fname), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines[:lines.index("---") + 1]) + "\n")
        return True
    return False

STORE_FILES = {"dispatch.md", "index.md", "ledger.md", "logger.md", "tombstones.md", "virtual.md",
               "session-storage.md", "local-storage.md", "data-store.md", "briefs.md"}
LOGGER_ENTRY_RE = re.compile(r"^- `\[(?:gate|guide|gc|inspector|looper)\]` 20\d\d-\d\d-\d\d(?: \d\d:\d\d)? — \*\*")
HEAD_RE = re.compile(r"^- ([a-z-]+):")
HEAD_VALUE_RE = re.compile(r'^(- [a-z-]+:\s*)"?(.*)$')   # the head's field prefix and its value, an opening quote dropped
FIELD_RE = re.compile(r"^  ([a-z-]+):")


def read(p):
    with open(p, encoding="utf-8", newline="") as f:
        return f.read()


def write(p, text):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ─── the record ─────────────────────────────────────────────────────────────────────────────────────────

def parse_record(text):
    """[(file, [block lines])] — blocks under each `## <file>` line, split at column-0 '- ' heads."""
    out, fname, cur = [], None, []
    for l in text.replace("\r\n", "\n").split("\n"):
        if l.startswith("## "):
            if fname and cur:
                out.append((fname, cur))
            fname, cur = l[3:].strip(), []
            continue
        if fname is None:
            continue
        if l.startswith("- ") and cur:
            out.append((fname, cur))
            cur = []
        if l.startswith("- ") or l.startswith("  ") or (cur and not l.strip()):
            if l.strip() or cur:
                cur.append(l)
    if fname and cur:
        out.append((fname, cur))
    return [(f, [l for l in b if l.strip() or True]) for f, b in out]


def trim(block):
    while block and not block[-1].strip():
        block.pop()
    return block


# ─── the store file ─────────────────────────────────────────────────────────────────────────────────────

def head_key(line):
    """A head line normalized for matching: trailing space and a closing quote dropped, and the value's opening
    quote dropped after the field name — so `- fingerprint: "what if` and `- fingerprint: what if` compare equal,
    whichever side the hook wrote and whichever the record gave."""
    key = line.rstrip().rstrip('"')
    m = HEAD_VALUE_RE.match(key)
    return f"{m.group(1)}{m.group(2)}" if m else key


class StoreFile:
    def __init__(self, path):
        self.path = path
        raw = read(path)
        self.crlf = "\r\n" in raw
        self.lines = raw.replace("\r\n", "\n").split("\n")
        try:
            self.sep = self.lines.index("---")
        except ValueError:
            self.sep = -1
        head = "\n".join(self.lines[:self.sep + 1]) if self.sep >= 0 else ""
        m = re.search(r"```yaml\n(.*?)```", head, re.S)
        self.shape = set(re.findall(r"^(?:- |  )([a-z-]+):", m.group(1), re.M)) if m else set()
        self.dirty = False

    def entries(self):
        """[(start, end)] half-open line ranges of entries after the separator."""
        out, i = [], self.sep + 1
        while i < len(self.lines):
            if self.lines[i].startswith("- "):
                j = i + 1
                while j < len(self.lines) and self.lines[j].startswith("  "):
                    j += 1
                out.append((i, j))
                i = j
            else:
                i += 1
        return out

    def find(self, head):
        """The entries whose head line begins with the block's head — the value's quotes ignored on both sides,
        since the prompt hook stores a fingerprint quoted and a record may give the same opening bare — or whose
        head is a TRUNCATED prefix of it: the prompt hook caps a fingerprint at FINGERPRINT_CHARS and closes it
        with `…`, so a block that gives the message whole must still find the row the hook stamped."""
        key = head_key(head).rstrip("…")
        out = []
        for s, e in self.entries():
            stored = head_key(self.lines[s])
            if stored.startswith(key):
                out.append((s, e))
                continue
            if stored.endswith("…") and len(stored) > 20 and key.startswith(stored[:-1]):
                out.append((s, e))
        return out

    def append(self, block):
        while self.lines and not self.lines[-1].strip():
            self.lines.pop()
        self.lines += [""] + block + [""]
        self.dirty = True

    def update(self, span, block):
        s, e = span
        changed = []
        for l in block[1:]:
            m = FIELD_RE.match(l)
            if not m:
                continue
            name = m.group(1)
            for i in range(s + 1, e):
                mm = FIELD_RE.match(self.lines[i])
                if mm and mm.group(1) == name:
                    self.lines[i] = l
                    break
            else:
                self.lines.insert(e, l)
                e += 1
            changed.append(name)
        self.dirty = True
        return changed

    def save(self):
        if not self.dirty:
            return
        text = "\n".join(self.lines)
        if not text.endswith("\n"):
            text += "\n"
        write(self.path, text.replace("\n", "\r\n") if self.crlf else text)


# ─── apply ──────────────────────────────────────────────────────────────────────────────────────────────

def check_times(block_text, now):
    bad = []
    if placeholder_times:
        bad += [f"placeholder time `{v}`" for v in placeholder_times(block_text)]
    if future_times:
        bad += [f"time `{v}` ahead of now ({now:{NOW_FMT}})" for v in future_times(block_text, now)]
    return bad


def apply_record(store, session, now, text, dry):
    files = {}
    written, updated, rows, refused = [], [], [], []
    for fname, block in parse_record(text):
        block = trim(block)
        if not block or not block[0].startswith("- "):
            continue
        head = block[0]
        if fname not in STORE_FILES:
            refused.append(f"{fname} — {head[:60]} — not a store file")
            continue
        path = os.path.join(store, fname)
        if not os.path.exists(path):
            seed_from_peer(store, fname)
        if not os.path.exists(path):
            refused.append(f"{fname} — {head[:60]} — file absent")
            continue
        sf = files.get(fname) or files.setdefault(fname, StoreFile(path))
        problems = check_times("\n".join(block), now)
        if fname == "logger.md":
            if not LOGGER_ENTRY_RE.match(head):
                problems.append("not the logger's tagged bullet shape")
        else:
            names = [m.group(1) for m in (HEAD_RE.match(head),) if m] + \
                    [FIELD_RE.match(l).group(1) for l in block[1:] if FIELD_RE.match(l)]
            unknown = [n for n in names if sf.shape and n not in sf.shape]
            if unknown:
                problems.append(f"field(s) not in the header shape: {', '.join(unknown)}")
        if problems:
            refused.append(f"{fname} — {head[:60]} — " + "; ".join(problems))
            continue
        matches = sf.find(head) if fname != "logger.md" else []
        if len(matches) > 1:
            refused.append(f"{fname} — {head[:60]} — ambiguous: {len(matches)} entries begin with it")
            continue
        if matches:
            changed = sf.update(matches[0], block)
            label = f"{fname} — {head[:60]} — {', '.join(changed) or 'no field'}"
            (rows if fname == "dispatch.md" else updated).append(label)
        else:
            sf.append(block)
            stamp = next((l.split(":", 1)[1].strip() for l in block if FIELD_RE.match(l) and l.startswith("  time:")), "")
            written.append(f"{fname} — {head[:60]}" + (f" — {stamp}" if stamp else ""))
    if not dry:
        for sf in files.values():
            sf.save()
    return written, updated, rows, refused


def run_check(store):
    phi = os.path.join(HERE, "phi.py")
    if not os.path.exists(phi):
        return "phi.py not found beside record.py — check skipped"
    r = subprocess.run([sys.executable, phi, "--store", store, "check"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    lines = (r.stdout or "").split("\n")
    keep = [l for l in lines if l.startswith(("[CORRUPT]", "[DEBT]", "[STRAY]", "phi.py check", "idb.py check"))]
    return "\n".join(keep) if keep else (r.stdout or "").strip()


LIGHT_MARKS = ("hook-poured dispatch record", "virtual", "logger.md:")


def derivation(session, now, written, updated, rows, refused, check, dry):
    out = [f"derivation — close, session {session[:8]}, {now:{NOW_FMT}} (mechanical: scripts/record.py"
           + (", dry run — nothing written)" if dry else ")")]
    out.append("written: " + ("\n  ".join([""] + written).strip() if written else "nothing"))
    out.append("updated: " + ("\n  ".join([""] + updated).strip() if updated else "nothing"))
    out.append("rows: " + ("\n  ".join([""] + rows).strip() if rows else "none completed"))
    out.append("refused: " + ("\n  ".join([""] + refused).strip() if refused else "nothing"))
    out.append("check: " + check.replace("\n", "\n  "))
    light = [l for l in check.split("\n") if l.startswith("[DEBT]") and any(m in l for m in LIGHT_MARKS)]
    judged = [l for l in check.split("\n") if l.startswith("[DEBT]") and l not in light]
    owed = []
    if light:
        owed.append(f"{len(light)} light debt(s) — the Stop hook's light sweep settles what a segment has room for")
    if judged:
        owed.append(f"{len(judged)} judged debt(s) — the operator's sweep moment")
    if refused:
        owed.append(f"{len(refused)} refused block(s) — rewrite and re-run the record")
    out.append("owed: " + ("; ".join(owed) if owed else "nothing"))
    return "\n".join(out)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="record.py", description="apply a VLDS record document — the mechanical close")
    ap.add_argument("--store", default=os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", "p4", "vlds"))
    ap.add_argument("--session", required=True)
    ap.add_argument("--now", required=True, help="the clock, YYYY-MM-DD HH:MM, copied from the hook stream")
    ap.add_argument("--record", required=True, help="the record document's path, or - for stdin")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    try:
        now = datetime.datetime.strptime(args.now, NOW_FMT)
    except ValueError:
        print(f"record.py: --now must read YYYY-MM-DD HH:MM, got {args.now!r}")
        return 2
    text = sys.stdin.read() if args.record == "-" else read(args.record)
    store = os.path.abspath(args.store)
    written, updated, rows, refused = apply_record(store, args.session, now, text, args.dry)
    check = run_check(store) if not args.dry else "(no check on a dry run)"
    print(derivation(args.session, now, written, updated, rows, refused, check, args.dry))
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
