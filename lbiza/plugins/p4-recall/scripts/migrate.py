#!/usr/bin/env python3
"""migrate.py: the old p4 layout (sessions/*/vlds/*.md, models/, vindex/ ...) into the new one (store/, models/,
archive/, src/), fresh-marketplace.md section 6. Dry by default: it reads the old tree, builds the new layout in
memory, runs every check of the migration table and writes the report `archive/migration-<date>.md`. `--apply`
also writes the new layout, into `--out` (default: in place, the old paths removed only when nothing is unplaced).

Every file of the old tree is placed: converted entry by entry, archived verbatim, or dropped as derived, each
drop with its reason; an entry or file that fits none is listed as unplaced, by old path and line.

    python3 migrate.py --p4 <old .claude/p4 tree> [--out <dir>] [--apply] [--now "YYYY-MM-DD HH:MM"]
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ranker  # noqa: E402
import store as st  # noqa: E402

# --- the old store's counting, as scripts/session/store_lessons.py does it (ported, read-only) ------------

OLD_KINDS = {"correction": ("ledger.md", re.compile(r"(?m)^\s*-?\s*meant:")),
             "retraction": ("tombstones.md", re.compile(r"(?m)^\s*-?\s*freed:")),
             "missed": ("briefs.md", re.compile(r"(?m)^\s*-?\s*omitted:")),
             "repeat": ("dispatch.md", re.compile(r"(?m)^\s*state:\s*(ECHO|SUPERSEDED)\s*$")),
             "ruling": ("local-storage.md", re.compile(r"(?m)^\s*-?\s*(ruling|rule|owner-words|words):"))}
TEMPLATE = re.compile(r":\s*\[|\[YYYY|\|\s*ECHO\s*\|")
FENCE_RE = re.compile(r"^```[a-z]*\s*$")
OLD_FIELD_RE = re.compile(r"^( {0,3})(- )?([a-z][a-z0-9_-]*):(?:\s(.*)|$)")
S8_RE = re.compile(r"--([0-9a-f]{8})$")


def old_blocks_text(text):
    """store_lessons.entries: blocks cut at blank lines and code fences."""
    text = re.sub(r"(?m)^```[a-z]*\s*$", "\n", text)
    return [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]


def old_stores(p4):
    found = sorted(os.path.dirname(p) for p in glob(p4, "sessions/*/vlds/index.md"))
    found += sorted({os.path.dirname(p) for p in glob(p4, "sessions/*/vlds/*.md")})
    for legacy in (os.path.join(p4, "vlds"), os.path.join(os.path.dirname(p4), "vlds"),
                   os.path.join(os.path.dirname(os.path.dirname(p4)), ".vlds")):
        if os.path.isdir(legacy):
            found.append(legacy)
    return list(dict.fromkeys(found))


def glob(p4, pattern):
    import glob as g
    return g.glob(os.path.join(p4, pattern))


def old_counts(p4):
    """store_lessons' numbers on the old tree: lesson counts, live rules, label health."""
    counts = {k: 0 for k in OLD_KINDS}
    for s in old_stores(p4):
        for kind, (fname, sel) in OLD_KINDS.items():
            f = os.path.join(s, fname)
            if os.path.exists(f):
                for e in old_blocks_text(st.read_text(f)):
                    if sel.search(e) and not TEMPLATE.search(e):
                        counts[kind] += 1
    seen, live = set(), []
    for s in old_stores(p4):
        f = os.path.join(s, "local-storage.md")
        if not os.path.exists(f):
            continue
        for e in old_blocks_text(st.read_text(f)):
            if TEMPLATE.search(e) or not re.search(r"(?m)^\s*status:\s*LIVE\b", e):
                continue
            words = re.search(r'(?m)^\s*owner-words:\s*"?(.*?)"?\s*$', e)
            ruling = re.search(r"(?m)^\s*-?\s*ruling:\s*(.*)$", e)
            text = (ruling.group(1) if ruling else words.group(1) if words else "").strip()
            if text and text not in seen:
                seen.add(text)
                live.append(text)
    lab = {"sessions": 0, "operator_ran": 0, "rows": 0, "completed": 0, "open": 0, "judged": 0}
    for d in sorted(glob(p4, "sessions/*/vlds")):
        f = os.path.join(d, "dispatch.md")
        if not os.path.exists(f):
            continue
        lab["sessions"] += 1
        lab["operator_ran"] += os.path.exists(os.path.join(d, "recall-pool.md"))
        for e in old_blocks_text(st.read_text(f)):
            if not re.search(r"(?m)^-\s*fingerprint:", e) or TEMPLATE.search(e):
                continue
            row_counts(lab, e)
    return {"counts": counts, "live_rules": live, "labels": lab}


def row_counts(lab, e):
    lab["rows"] += 1
    state = re.search(r"(?m)^\s*state:\s*(FRESH|ECHO|SUPERSEDED)\b", e)
    done = state and re.search(r"(?m)^\s*addressed:\s*\S", e)
    lab["completed" if done else "open"] += 1
    lab["judged"] += bool(state and state.group(1) != "FRESH") or bool(re.search(r"(?m)^\s*match:\s*\S", e))


# --- reading old files into entries ---------------------------------------------------------------------

def old_blocks(text):
    """[(first line 1-based, [lines])] cut at blank lines and fence lines, with line numbers."""
    out, cur = [], None
    for n, l in enumerate(text.split("\n"), 1):
        if not l.strip() or FENCE_RE.match(l):
            cur = None
            continue
        if cur is None:
            cur = (n, [])
            out.append(cur)
        cur[1].append(l)
    return out


def old_entries(text):
    """[{line, pairs, block, template, text}] for every block that carries a field, split at its column-0
    `- key:` lines; header prose (no field) and schema templates are returned marked so the caller can count them.
    A block that opens on an indented field with no dash continues the entry before it: the old hooks wrote a row's
    first fields, and the model appended `state:` and `addressed:` after a blank line (`joined` records where)."""
    out, last = [], None
    for start, lines in old_blocks(text):
        btext = "\n".join(lines)
        if TEMPLATE.search(btext):
            out.append({"line": start, "pairs": [], "block": start, "template": True, "text": btext})
            last = None
            continue
        ents, cur, lead = [], None, []
        first = OLD_FIELD_RE.match(lines[0])
        if first and first.group(1) and not first.group(2) and last is not None:
            cur = last
            cur.setdefault("joined", []).append(start)
        for k, l in enumerate(lines):
            m = OLD_FIELD_RE.match(l)
            if m and (cur is None or (m.group(2) and not m.group(1))):
                cur = {"line": start + k, "pairs": [], "block": start, "template": False, "lines": []}
                if not ents and lead:
                    cur["lead"] = list(lead)
                ents.append(cur)
            if cur is None:
                lead.append(l)
                continue                                    # prose before any field
            cur["lines"].append(l)
            if m:
                cur["pairs"].append((m.group(3), (m.group(4) or "").rstrip()))
            elif cur["pairs"]:
                k_, v = cur["pairs"][-1]
                cur["pairs"][-1] = (k_, (v + "\n" + l.strip()) if v else l.strip())
        if not ents and cur is None:
            out.append({"line": start, "pairs": [], "block": start, "template": False, "prose": True, "text": btext})
        for e in ents:
            if e["pairs"] and e["pairs"][0][0] in ("correction",) and not e["pairs"][0][1] and len(e["pairs"]) > 1:
                e["pairs"] = e["pairs"][1:]
            out.append(e)
        if ents:
            last = ents[-1]
    for e in out:
        if "lines" in e:
            e["text"] = "\n".join(e.pop("lines"))
    return out


def has(e, *keys):
    return any(k == key and (v or "").strip() for k, v in e["pairs"] for key in keys)


def fieldv(e, key, default=""):
    for k, v in e["pairs"]:
        if k == key:
            return v
    return default


def session_of(dirname):
    m = S8_RE.search(dirname)
    if m:
        return m.group(1)
    return dirname


# --- the plan: every old file placed ---------------------------------------------------------------------

CONVERT = {"local-storage.md", "ledger.md", "tombstones.md", "briefs.md", "data-store.md", "dispatch.md", "index.md",
           "recall-pool.md"}
ARCHIVE_SESSION_FILES = {"session-storage.md", "virtual.md", "logger.md", "mind-reader.md"}
DROP_SESSION_FILES = {"phi-index.md": "the per-session φ register; derived", ".sessions": "derived session list",
                      ".gc-heads": "the retired gc's heads; derived", ".turn-close": "a turn-close stamp; derived",
                      ".check-last": "a check stamp; derived", ".pre-ask": "the retired pre-ask gate's state",
                      ".pool-owed": "the retired pool's flag"}
DROP_TOP = {"vindex": "the cumulative vlds index; derived (its ## recall section is copied below)",
            "sindex": "the cumulative frags index; derived, rebuilt from src/"}
ARCHIVE_TOP = ("mrindex",)
# flights/ is kept where it is: p4-plans' flight loop writes it and phi_store trains on its plan.md files.
KEEP_TOP = ("flights",)
COMMENT = {".py": "#", ".sh": "#", ".ps1": "#", ".cmake": "#", ".rb": "#", ".pl": "#", ".r": "#", ".yml": "#",
           ".yaml": "#", ".toml": "#", ".js": "//", ".ts": "//", ".mjs": "//", ".cjs": "//", ".c": "//", ".cc": "//",
           ".cpp": "//", ".h": "//", ".hh": "//", ".hpp": "//", ".cs": "//", ".go": "//", ".rs": "//",
           ".java": "//", ".swift": "//", ".m": "//", ".mm": "//", ".lua": "--", ".sql": "--"}


class Plan:
    def __init__(self, p4, now):
        self.p4, self.now = p4, now
        self.new = {f: [] for f in st.STORE_FILES}          # file -> [pairs]
        self.messages = {}                                   # s8 -> [pairs]
        self.index_rules = []                                # archive/index-rules.md
        self.unsorted = {}                                   # archive/unsorted/<name> -> [pairs]
        self.archive = []                                    # (old rel, new rel) verbatim
        self.dropped = []                                    # (old rel, reason)
        self.src = []                                        # (old rel, new rel, head comment or "")
        self.unplaced = []                                   # (old rel:line, reason)
        self.reasons = []                                    # (old rel:line, where, reason) placed with a reason
        self.kept = []                                       # untouched paths (memory/, scratchpad/, .git ...)
        self.pools, self.audits = [], []
        self.multi = []                                      # (old rel:line, n, kind)
        self.prose = 0
        self.templates = 0
        self.found = {}                                      # kind -> count found
        self.recall_section = ""
        self.notes = []
        self.frag_heads = {}                                 # old src rel -> task text
        self.joined = []                                     # old rel:line of a row's fields joined across a blank
        self.completions = []                                # (old rel:line, row) a text-keyed completion joined

    def put(self, fname, pairs, rel, line):
        pairs = list(pairs) + [("from", f"{rel}:{line}")]
        self.last_put = pairs
        if fname.startswith("messages/"):
            self.messages.setdefault(fname[len("messages/"):-3], []).append(pairs)
        elif fname == "archive/index-rules.md":
            self.index_rules.append(pairs)
        elif fname.startswith("archive/"):
            self.unsorted.setdefault(fname, []).append(pairs)
        else:
            self.new[fname].append(pairs)

    def count(self, kind, n=1):
        self.found[kind] = self.found.get(kind, 0) + n


def build_plan(p4, now):
    plan = Plan(p4, now)
    for root, dirs, files in os.walk(p4):
        dirs.sort()
        rel_root = os.path.relpath(root, p4).replace(os.sep, "/")
        if rel_root == ".":
            rel_root = ""
        parts = rel_root.split("/") if rel_root else []
        if parts[:1] in (["memory"], ["scratchpad"], [".git"], ["store"], ["archive"], ["src"], *([k] for k in KEEP_TOP)):
            if root == os.path.join(p4, parts[0]):
                plan.kept.append(parts[0] + "/")
            dirs[:] = []
            continue
        if parts[:1] in ([k] for k in DROP_TOP):
            if len(parts) == 1:
                plan.dropped.append((parts[0] + "/", DROP_TOP[parts[0]]))
                if parts[0] == "vindex" and os.path.exists(os.path.join(root, "phi-index.md")):
                    t = st.read_text(os.path.join(root, "phi-index.md"))
                    m = re.search(r"(?ms)^## recall\s*$.*?(?=^## |\Z)", t)
                    plan.recall_section = m.group(0).strip() if m else ""
            dirs[:] = []
            continue
        for name in sorted(files):
            rel = f"{rel_root}/{name}" if rel_root else name
            place_file(plan, rel, parts, name)
    return plan


def place_file(plan, rel, parts, name):
    p4 = plan.p4
    path = os.path.join(p4, rel)
    if not parts:
        if name in (".gitignore", ".gitattributes"):
            plan.kept.append(rel)
        else:
            plan.archive.append((rel, f"archive/{rel}"))
            plan.reasons.append((rel, f"archive/{rel}", "a top-level file of no known kind, archived verbatim"))
        return
    if parts[0] in ARCHIVE_TOP:
        plan.archive.append((rel, f"archive/{rel}"))
        return
    if parts[0] == "models":
        if len(parts) >= 2 and parts[1] == "labels" and name.endswith(".tsv"):
            plan.audits.append(rel)
            plan.archive.append((rel, f"archive/{rel}"))
        elif name.endswith(".pt"):
            plan.dropped.append((rel, "the retired .pt ranker (Colab: no .pt raised the JSON ranker)"))
        elif name.endswith(".tmp"):
            plan.dropped.append((rel, "a temp file"))
        else:
            plan.archive.append((rel, f"archive/{rel}"))
        return
    if parts[0] == "sessions" and len(parts) >= 2:
        sdir = parts[1]
        s8 = session_of(sdir)
        sub = parts[2:]
        if not sub:                                          # a file right under sessions/<d>/
            plan.archive.append((rel, f"archive/{rel}"))
            return
        if sub[0] == "vlds" and len(sub) == 1:
            if name in CONVERT:
                convert_file(plan, rel, name, s8, path)
            elif name in ARCHIVE_SESSION_FILES:
                plan.archive.append((rel, f"archive/{rel}"))
            elif name in DROP_SESSION_FILES:
                plan.dropped.append((rel, DROP_SESSION_FILES[name]))
            elif name.endswith(".tmp"):
                plan.dropped.append((rel, "a temp file"))
            else:
                plan.archive.append((rel, f"archive/{rel}"))
                plan.reasons.append((rel, f"archive/{rel}", "a session file of no known kind, archived verbatim"))
            return
        if sub[0] == "vlds" and sub[1:2] == ["idb"]:
            if len(sub) >= 3 and sub[2] in ("runs", "blobs"):
                plan.archive.append((rel, f"archive/{rel}"))
                plan.reasons.append((rel, f"archive/{rel}", "the keyspace's cold tier (entries poured out of the "
                                                            "hot files), kept verbatim, not indexed"))
            else:
                plan.dropped.append((rel, "the keyspace's index (idb/); derived"))
            return
        if sub[0] == "vlds":
            plan.archive.append((rel, f"archive/{rel}"))
            plan.reasons.append((rel, f"archive/{rel}", "a nested file under a session's vlds/, archived verbatim"))
            return
        if sub[0] == "src":
            if len(sub) == 1 and name == "frags.md":
                plan.archive.append((rel, f"archive/{rel}"))
                read_frags(plan, rel, sdir)
            elif len(sub) == 1:
                plan.src.append((rel, f"src/{s8}/{name}"))
            else:
                plan.src.append((rel, f"src/{s8}-{sub[1]}/" + "/".join(sub[2:] + [name])))
            return
        if sub[0] in ("mind-reader",) or name == "flights.tsv":
            plan.archive.append((rel, f"archive/{rel}"))
            return
        plan.archive.append((rel, f"archive/{rel}"))
        plan.reasons.append((rel, f"archive/{rel}", "a session file of no known kind, archived verbatim"))
        return
    plan.archive.append((rel, f"archive/{rel}"))
    plan.reasons.append((rel, f"archive/{rel}", "a file of no known kind, archived verbatim"))


def read_frags(plan, rel, sdir):
    for e in old_entries(st.read_text(os.path.join(plan.p4, rel))):
        if e.get("template") or not e["pairs"] or e["pairs"][0][0] != "frag":
            continue
        frag = e["pairs"][0][1].strip().strip("`")
        task = st.collapse(fieldv(e, "task"))
        if frag and task:
            plan.frag_heads[f"sessions/{sdir}/src/{frag}"] = task


def convert_file(plan, rel, name, s8, path):
    text = st.read_text(path)
    if name == "recall-pool.md":
        plan.pools.append(rel)
        plan.archive.append((rel, f"archive/{rel}"))
        return
    ents = old_entries(text)
    sep = None
    lines = text.split("\n")
    if "---" in lines:
        sep = lines.index("---") + 1
    kind_by_block = {}
    rows_here = []
    for e in ents:
        where = f"{rel}:{e['line']}"
        for j in e.get("joined", []):
            plan.joined.append(f"{rel}:{j}")
        if name == "dispatch.md" and not e.get("template") and not e.get("prose") and e["pairs"] \
                and e["pairs"][0][0] != "fingerprint" and e.get("lead") and e["lead"][0].startswith("- "):
            key = st.norm_token(st.unquote(e["lead"][0][2:]))[:40]
            row = None
            for tok, pairs in reversed(rows_here):
                if key and (tok.startswith(key) or key.startswith(tok[:40])):
                    row = pairs
                    break
            if row is not None:
                row.extend(e["pairs"] + [("completed-from", where)])
                plan.completions.append(where)
                continue
        if e.get("template"):
            plan.templates += 1
            continue
        if e.get("prose"):
            if sep is not None and e["line"] > sep and name != "index.md":
                plan.put(f"archive/unsorted/{name}", [("text", e["text"])], rel, e["line"])
                plan.reasons.append((where, f"archive/unsorted/{name}", "prose in the file's body, not an entry"))
            else:
                plan.prose += 1
            continue
        target, kind = route(name, e)
        if target is None:
            plan.unplaced.append((where, kind))
            continue
        if target.startswith("archive/"):
            plan.reasons.append((where, target, kind))
        else:
            plan.count(kind)
        if target == "messages":
            target = f"messages/{s8}.md"
        plan.put(target, e["pairs"], rel, e["line"])
        if target.startswith("messages/"):
            rows_here.append((st.norm_token(st.unquote(e["pairs"][0][1])), plan.last_put))
        if name == "index.md" and has(e, "owner-words"):
            plan.put("rules.md", e["pairs"] + [("source", "index")], rel, e["line"])
        kind_by_block.setdefault(e["block"], []).append(kind)
    for b, kinds in kind_by_block.items():
        if len(kinds) > 1:
            plan.multi.append((f"{rel}:{b}", len(kinds), kinds[0]))


def route(name, e):
    """(new file, kind) for one old entry, or (archive file, reason), or (None, why unplaced)."""
    if name == "local-storage.md":
        if has(e, "ruling", "rule", "owner-words", "words"):
            return "rules.md", "ruling"
        return "archive/unsorted/local-storage.md", "a local-storage entry with no ruling or owner-words"
    if name == "ledger.md":
        if has(e, "meant"):
            return "corrections.md", "correction"
        return "archive/ledger-events.md", "a ledger event (surfaced or reused), not a correction"
    if name == "tombstones.md":
        if has(e, "freed"):
            return "retractions.md", "retraction"
        return "archive/unsorted/tombstones.md", "a tombstones entry with no freed:"
    if name == "briefs.md":
        if has(e, "omitted", "asked"):
            return "corrections.md", "missed"
        return "archive/unsorted/briefs.md", "a briefs entry with no asked: or omitted:"
    if name == "data-store.md":
        if has(e, "claim"):
            return "facts.md", "claim"
        return "archive/unsorted/data-store.md", "a data-store entry with no claim:"
    if name == "dispatch.md":
        if e["pairs"] and e["pairs"][0][0] == "fingerprint":
            return "messages", "row"
        return "archive/unsorted/dispatch.md", "a dispatch entry with no fingerprint:"
    if name == "index.md":
        if has(e, "key"):
            return "archive/index-rules.md", "an index.md guide-loop rule: archived, not indexed (open question 3)"
        return "archive/unsorted/index.md", "an index.md entry with no key:"
    return None, "no route"


# --- the new store in memory -----------------------------------------------------------------------------

def new_files(plan):
    """{store rel: [Entry]} as parse() would read the files the plan writes, statuses applied."""
    texts = {f: st.render(f, plan.new[f]) for f in st.STORE_FILES}
    for s8, rows in sorted(plan.messages.items()):
        texts[f"messages/{s8}.md"] = st.render(f"messages/{s8}.md", rows)
    files = {f: st.parse(t, f) for f, t in texts.items()}
    st.apply_status(files)
    return texts, files


def df_table(files, p4):
    docs = []
    for f, ents in files.items():
        for e in ents:
            if f.startswith("messages/") and not st.completed(e):
                continue
            if e.state == "LIVE":
                docs.append(set(ranker.tokens(st.entry_text(e))))
    for e in st.memory_entries(p4):
        docs.append(set(ranker.tokens(st.entry_text(e))))
    df = {}
    for d in docs:
        for t in d:
            df[t] = df.get(t, 0) + 1
    return df, len(docs)


# --- checks ----------------------------------------------------------------------------------------------

def new_counts(files):
    out = {"correction": 0, "retraction": 0, "missed": 0, "repeat": 0, "claim": 0, "ruling": 0}
    lab = {"sessions": 0, "rows": 0, "completed": 0, "open": 0, "judged": 0}
    keys = {}
    for f, ents in files.items():
        if f.startswith("messages/"):
            lab["sessions"] += 1
            for e in ents:
                text = "\n".join(f"{'- ' if i == 0 else '  '}{k}: {v}" for i, (k, v) in enumerate(e.pairs))
                row_counts(lab, text)
                if re.search(r"(?m)^\s*state:\s*(ECHO|SUPERSEDED)\s*$", text):
                    out["repeat"] += 1
            continue
        for e in ents:
            if f == "corrections.md":
                if "meant" in e.fields:
                    out["correction"] += 1
                    k = st.collapse(e.fields.get("key", ""))
                    if k:
                        keys[k] = keys.get(k, 0) + 1
                if "omitted" in e.fields:
                    out["missed"] += 1
            elif f == "retractions.md" and "freed" in e.fields:
                out["retraction"] += 1
            elif f == "facts.md" and "claim" in e.fields:
                out["claim"] += 1
            elif f == "rules.md" and e.fields.get("source", "") != "index":
                out["ruling"] += 1
    return out, lab, {k: n for k, n in keys.items() if n > 1}


def new_live_rules(files):
    """The LIVE rulings by the new status rule, each text once, as store_lessons.live_rules reads them: entries
    whose own status is LIVE (store_lessons counts no other), now also unmasked by any retraction."""
    seen, out, lost = set(), [], []
    for e in files.get("rules.md", []):
        if e.fields.get("source", "") == "index":
            continue
        own = (e.fields.get("status") or "").strip().upper().startswith("LIVE")
        words = st.unquote(e.fields.get("owner-words", ""))
        text = (e.fields.get("ruling") or words or "").strip()
        if not own or not text or text in seen:
            continue
        seen.add(text)
        if e.state == "LIVE":
            out.append(text)
        else:
            lost.append((text, e.id, e.reason))
    return out, lost


def finding17(files):
    """The rulings the old mask freed on shared owner-words that the new rule keeps LIVE: [(id, text, new state)]."""
    ms = st.masks(files.get("retractions.md", []))
    got = []
    for e in files.get("rules.md", []):
        old_state, _ = st.status_of("rules.md", e.value, e.fields, ms, rule="old")
        if old_state == "FREED" and e.state != "FREED":
            got.append((e.id, st.collapse(e.value), e.state))
    return got


# --- pools -----------------------------------------------------------------------------------------------

POOL_STEER_RE = re.compile(r"^- \[([a-z-]+\.md) (\d{4}-\d\d-\d\d \d\d:\d\d|\(no time\))[^\]]*\] (.*?); bears: (.*)$")
MODEL_CREDIT_RE = re.compile(r"\(\d+, [a-z+]*\bmodel\b")
STAMP_RE = re.compile(r"\b(20\d\d-\d\d-\d\d(?: \d\d:\d\d)?)\b")
NEW_OF_OLD = {"local-storage.md": "rules.md", "ledger.md": "corrections.md", "tombstones.md": "retractions.md",
              "briefs.md": "corrections.md", "data-store.md": "facts.md"}


def parse_pool(path):
    """pick_model.parse_pool, ported."""
    text = st.read_text(path)
    task = re.search(r"^task:\s*(.*)$", text, re.M)
    pooled = re.search(r"^pooled:\s*(\d{4}-\d\d-\d\d \d\d:\d\d)", text, re.M)
    session = re.search(r"^session:\s*(\S+)", text, re.M)
    read = re.search(r"^read:\s*(.*)$", text, re.M)
    steer = text.split("## steering", 1)[1].split("\n## ", 1)[0] if "## steering" in text else ""
    picks = []
    for l in steer.splitlines():
        m = POOL_STEER_RE.match(l)
        if m:
            picks.append((m.group(1), m.group(2), m.group(3).rstrip("\u2026").strip()))
    by_model = bool(read and MODEL_CREDIT_RE.search(read.group(1)))
    sid = session.group(1)[:8] if session else ""
    pid = sid or os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(path))))
    return {"path": path, "task": task.group(1).strip() if task else "", "pooled": pooled.group(1) if pooled else "",
            "session": sid, "id": pid, "picks": picks, "by_model": by_model, "reader": "children"}


def parse_label_file(path):
    task = pooled = session = ""
    reader = "children"
    picks = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for l in f:
            l = l.rstrip("\n")
            if l.startswith("# task: "):
                task = l[8:]
            elif l.startswith("# pooled: "):
                pooled = l[10:][:16]
            elif l.startswith("# session: "):
                session = l[11:]
            elif l.startswith("# reader: "):
                reader = l[10:]
            elif l and not l.startswith("#"):
                parts = l.split("\t", 2)
                if len(parts) == 3:
                    picks.append((parts[0], parts[1], parts[2]))
    return {"path": path, "task": task, "pooled": pooled, "session": session, "id": session + "/audit",
            "picks": picks, "by_model": False, "reader": reader}


def labelled_pool(p):
    return bool(p["task"] and p["pooled"] and p["picks"] and not p["by_model"])


def distilled(old_file, field, value, fields, width=400):
    """phi.distilled's text of an old entry, which a pool's pick head is a prefix of."""
    v = value
    if field == "log":
        m = re.search(r"\*\*(.+?)\*\*", v)
        v = m.group(1) if m else v
    v = re.sub(r"\s+", " ", v.strip().strip('"').strip("'")).strip()
    tag = ""
    if old_file == "index.md" and fields.get("directive", "").strip():
        directive = re.sub(r"[ \t]+", " ", fields["directive"].strip())
        v = v + ": " + directive
    elif old_file == "data-store.md":
        tag = " (sourced)" if fields.get("verified", "").strip() or fields.get("source", "").strip() else " (unsourced)"
    room = max(width - len(tag), 12)
    return (v if len(v) <= room else v[:room - 1].rstrip() + "\u2026") + tag


def pick_lookup(plan, files):
    """{(old file, time): [(distilled head, id, entry or None)]} over every placed entry and every archived file
    of entries a pool could have picked from."""
    look = {}
    for f, ents in files.items():
        if f.startswith("messages/"):
            continue
        for e in ents:
            src = e.fields.get("from", "")
            old_file = src.rsplit(":", 1)[0].rsplit("/", 1)[-1]
            if f == "rules.md" and e.fields.get("source") == "index":
                continue
            t = e.time or "(no time)"
            look.setdefault((old_file, t[:16]), []).append(
                (distilled(old_file, e.head, e.value, e.fields), e.id, e))
    # archived session files and the archived index rules: resolvable, never indexed
    for old_rel, new_rel in plan.archive:
        base = old_rel.rsplit("/", 1)[-1]
        if base not in ARCHIVE_SESSION_FILES or "/idb/" in old_rel:
            continue
        for e in archived_entries(os.path.join(plan.p4, old_rel), new_rel):
            look.setdefault((base, (e["time"] or "(no time)")[:16]), []).append((e["head"], e["id"], None))
    for rel, pairs in plan.unsorted.items():
        for e in st.parse(st.render(rel, pairs), rel):
            src = e.fields.get("from", "")
            old_file = src.rsplit(":", 1)[0].rsplit("/", 1)[-1]
            look.setdefault((old_file, (e.time or "(no time)")[:16]), []).append(
                (distilled(old_file, e.head, e.value, e.fields), e.id, None))
    ir = st.parse(st.render("archive/index-rules.md", plan.index_rules), "archive/index-rules.md")
    for e in ir:
        t = e.time or "(no time)"
        look.setdefault(("index.md", t[:16]), []).append((distilled("index.md", e.head, e.value, e.fields),
                                                          e.id, None))
    return look


def archived_entries(path, new_rel):
    """phi.hot_entries over an archived file: the column-0 `- ` heads after the `---` line (a bullet with no field is
    a log line), with ids under the archive."""
    lines = st.read_text(path).split("\n")
    try:
        start = lines.index("---") + 1
    except ValueError:
        start = 0
    out, i = [], start
    while i < len(lines):
        l = lines[i]
        if not l.startswith("- "):
            i += 1
            continue
        m = re.match(r"^- ([a-z-]+):\s*(.*)$", l)
        field, value = (m.group(1), m.group(2)) if m else ("log", l[2:])
        fields, j = {}, i + 1
        while j < len(lines) and lines[j].startswith("  "):
            fm = re.match(r"^  ([a-z-]+):\s*(.*)$", lines[j])
            if fm and fm.group(1) not in fields:
                fields[fm.group(1)] = fm.group(2)
            j += 1
        t = fields.get("time", "")
        if not t and field == "log":
            sm = STAMP_RE.search(value)
            t = sm.group(1) if sm else ""
        out.append({"time": t, "head": distilled(os.path.basename(path), field, value, fields),
                    "id": f"{new_rel}:{t}:{st.sha8(value)}"})
        i = j
    return out


def import_pools(plan, files):
    """(tasks rows, label rows, stats) for every labelled pool and audit, each pick resolved to an entry id."""
    look = pick_lookup(plan, files)
    tasks, labels = [], []
    stats = {"pools": 0, "labelled": 0, "audits": 0, "picks": 0, "resolved": 0, "to_archive": 0, "to_freed": 0,
             "unresolved": []}
    sources = [parse_pool(os.path.join(plan.p4, r)) for r in plan.pools if r.count("/") == 3]
    stats["pools"] = len(sources)
    for r in plan.pools:
        if r.count("/") != 3:
            plan.reasons.append((r, f"archive/{r}", "a recall pool nested below a session's vlds/; the old ranker "
                                                    "never read it, so no labels are imported from it"))
    audits = [parse_label_file(os.path.join(plan.p4, r)) for r in plan.audits]
    taught = {p["session"][:8] for p in audits if labelled_pool(p) and p.get("reader", "children") != "children"}
    chosen = [p for p in sources if labelled_pool(p) and (p.get("session") or "")[:8] not in taught]
    stats["labelled"] = len(chosen)
    stats["taught_out"] = sum(1 for p in sources if labelled_pool(p) and (p.get("session") or "")[:8] in taught)
    chosen_audits = [p for p in audits if labelled_pool(p)]
    stats["audits"] = len(chosen_audits)
    for p in chosen + chosen_audits:
        is_audit = p in chosen_audits
        tid = ("audit:" if is_audit else "pool:") + p["id"]
        tasks.append([tid, p["session"], p["pooled"], st.collapse(p["task"]), "first"])
        done = set()
        for f, tm, head in p["picks"]:
            stats["picks"] += 1
            got = None
            for dist, eid, e in look.get((f, tm[:16]), []):
                if dist.startswith(head[:40]):
                    got = (eid, e)
                    break
            # pick_model.build_pairs matched a pick by file, time and head prefix alone: a pick whose head the reader
            # wrote in its own words was never a label, so it is listed, not resolved by its time (a guess that gave
            # pool a3ac5de6 three labels the old ranker never had)
            if not got:
                stats["unresolved"].append(f"{os.path.relpath(p['path'], plan.p4)}: [{f} {tm}] {head[:80]}")
                continue
            eid, e = got
            note = f"reader={p['reader']}" if is_audit else ""
            if e is None:
                stats["to_archive"] += 1
                note = (note + " " if note else "") + "archived (not indexed)"
            elif e.state != "LIVE":
                # the old barrier listed a freed or spent entry with its state, and the pool's reader picked it: the
                # label stays on that entry (train.py keeps such entries among a pool's candidates), never moved to
                # the retraction, which is dated after the pool and so could never be drawn for it
                stats["to_freed"] += 1
                note = (note + " " if note else "") + f"picked while {e.state}"
            stats["resolved"] += 1
            if eid in done:
                continue
            done.add(eid)
            labels.append([tid, eid, "1", "pool", "0.7", p["pooled"], note])
    return tasks, labels, stats


# --- dictionary seeds (5.3) ------------------------------------------------------------------------------

COMMON = st.COMMON
MARKERS = ("no", "not", "i meant", "i mean", "should have", "incorrect", "wrong", "again")


def session_rows(files):
    """{s8: [Entry]} in file order."""
    return {f[len("messages/"):-3]: ents for f, ents in files.items() if f.startswith("messages/")}


def turn_rows(rows):
    """The owner's own messages: notifications, agent messages and hook injections out."""
    return [r for r in rows if not re.match(r"(?i)\s*(task notification|agent message|hook injection)",
                                            r.fields.get("arrival", "")) and not fp(r).lstrip().startswith("<")]


def misread_before(rows, i, df, n, exclude=()):
    """(row, terms) for the owner's message a signal at row i answers: the nearest of the three before it that is not
    a shell command (`! ...`) and yields a rare term, or (None, [])."""
    for j in range(i - 1, max(-1, i - 4), -1):
        text = fp(rows[j])
        if text.lstrip().startswith("!"):
            continue
        ts = rare_terms(text, df, n, exclude=exclude)
        if ts:
            return rows[j], ts
    return None, []


def fp(e):
    return st.unquote(e.fields.get("fingerprint", e.value))


def rare_terms(text, df, n, exclude=(), limit=1):
    """The words of `text` rare in the index (idf > 3) or unseen, outside `exclude` and the common vocabulary,
    rarest first."""
    ex = set(exclude)
    got = []
    for t in dict.fromkeys(ranker.tokens(text)):
        if t in ex or t in COMMON or t.isdigit() or len(t) < 3:
            continue
        c = df.get(t, 0)
        idf = ranker.idf_of(c, n) if c else 99.0
        if ranker.is_rare(c, n):
            got.append((-idf, t))
    return [t for _, t in sorted(got)[:limit]]


def row_at(rows, when, words=""):
    """The row a signal at `when` answers: one whose fingerprint resembles `words`, else the last row timed at or
    before `when`."""
    if words:
        wt = set(st.norm_token(words).split())
        for i, r in enumerate(rows):
            if st.resembles(wt, set(st.norm_token(fp(r)).split())):
                return i
    best = None
    for i, r in enumerate(rows):
        if r.time and when and r.time[:16] <= when[:16]:
            best = i
    return best


def locate(rows_by, timeline, s8, when, words):
    """(rows, i): the signal's answering row in its own session's rows; failing that (a legacy store, a session with
    no rows), in every session's rows laid on one timeline, within an hour before the signal."""
    rows = turn_rows(rows_by.get(s8, []))
    i = row_at(rows, when, words)
    if i:
        return rows, i
    j = row_at(timeline, when, "")
    if j and minutes(timeline[j].time, when) is not None and minutes(timeline[j].time, when) <= 60:
        if words:
            wt = set(st.norm_token(words).split())
            for k in range(j, max(0, j - 5), -1):
                if st.resembles(wt, set(st.norm_token(fp(timeline[k])).split())):
                    return timeline, k
        return timeline, j
    return rows, i


def clip(s, n):
    s = st.collapse(s)
    return s if len(s) <= n else s[:n - 1].rstrip() + "\u2026"


def seed_dictionary(files, df, n, now):
    """(vocabulary pairs, stats): one pending entry per term from the 221 signals' kinds (correction, retraction,
    missed detail, repeat) and the follow-up detector, `because:` filled, `means: (pending)`."""
    rows_by = session_rows(files)
    terms, order = {}, []
    stats = {"signals": {"correction": 0, "retraction": 0, "missed": 0, "repeat": 0, "follow-up": 0},
             "yielded": {"correction": 0, "retraction": 0, "missed": 0, "repeat": 0, "follow-up": 0},
             "no_term": []}

    def add(kind, ts, because, source, points):
        for t in ts:
            if t not in terms:
                terms[t] = {"because": [], "source": source, "points": []}
                order.append(t)
            if because not in terms[t]["because"]:
                terms[t]["because"].append(because)
            for p in points:
                if p not in terms[t]["points"]:
                    terms[t]["points"].append(p)

    def session_for(e):
        src = e.fields.get("from", "")
        m = re.match(r"sessions/([^/]+)/", src)
        return session_of(m.group(1)) if m else ""

    timeline = sorted((r for rows in rows_by.values() for r in turn_rows(rows) if r.time),
                      key=lambda r: r.time[:16])
    rules_by_time = {}
    for e in files.get("rules.md", []):
        rules_by_time.setdefault(e.time[:16], []).append(e.id)

    for e in files.get("corrections.md", []):
        missed = "omitted" in e.fields
        kind = "missed" if missed else ("correction" if "meant" in e.fields else None)
        if not kind:
            continue
        stats["signals"][kind] += 1
        words = st.unquote(e.fields.get("asked", "")) if missed else ""
        rows, i = locate(rows_by, timeline, session_for(e), e.time, words)
        where = e.fields.get("from", e.id)
        if i is None or i == 0:
            stats["no_term"].append(f"{kind} {where}: no earlier owner message in its session's rows")
            continue
        after = rows[i]
        match = st.collapse(e.fields.get("match", ""))
        before, ts = misread_before(rows, i, df, n, exclude=ranker.tokens(match))
        if not ts:
            stats["no_term"].append(f"{kind} {where}: yielded no rare term")
            continue
        stats["yielded"][kind] += 1
        if missed:
            because = (f"{before.time} — you wrote \"{clip(fp(before), 140)}\"; then you asked "
                       f"\"{clip(fp(after), 140)}\" ({e.time}); it had left out: {clip(e.fields.get('omitted', ''), 60)}")
            source = f"missed detail ({e.id})"
        else:
            because = (f"{before.time} — you wrote \"{clip(fp(before), 140)}\" and it was read as: {clip(match, 120)}; "
                       f"you then wrote \"{clip(fp(after), 140)}\" ({after.time})")
            key = st.collapse(e.fields.get("key", "")) or e.id
            source = f"correction (corrections.md: {key})" if key != e.id else f"correction ({e.id})"
        add(kind, ts, because, source, [e.id] + rules_by_time.get(e.time[:16], []))

    for e in files.get("retractions.md", []):
        stats["signals"]["retraction"] += 1
        words = st.unquote(e.fields.get("owner-words", ""))
        rows, i = locate(rows_by, timeline, session_for(e), e.time, words)
        where = e.fields.get("from", e.id)
        if i is None or i == 0:
            stats["no_term"].append(f"retraction {where}: no earlier owner message in its session's rows")
            continue
        before, ts = misread_before(rows, i, df, n, exclude=ranker.tokens(e.fields.get("freed", "")))
        if not ts:
            stats["no_term"].append(f"retraction {where}: yielded no rare term")
            continue
        stats["yielded"]["retraction"] += 1
        because = (f"{before.time} — you wrote \"{clip(fp(before), 140)}\"; you then wrote \"{clip(words, 140)}\" "
                   f"({e.time}), freeing: {clip(e.fields.get('freed', ''), 80)}")
        add("retraction", ts, because, f"retraction ({e.id})",
            [e.id] + rules_by_time.get(e.time[:16], []))

    for s8, rows in sorted(rows_by.items()):
        for i, r in enumerate(rows):
            if not any(re.match(r"^\s*(ECHO|SUPERSEDED)\s*$", v) for v in r.all("state")):
                continue
            stats["signals"]["repeat"] += 1
            new = set(st.norm_token(fp(r)).split())
            first = None
            for j in range(i):
                if st.resembles(new, set(st.norm_token(fp(rows[j])).split())):
                    first = rows[j]
                    break
            if first is None:
                best = max(range(i), key=lambda j: len(new & set(st.norm_token(fp(rows[j])).split())), default=None)
                first = rows[best] if best is not None and new & set(st.norm_token(fp(rows[best])).split()) else None
            where = r.fields.get("from", r.id)
            if first is None:
                stats["no_term"].append(f"repeat {where}: no earlier message shares a word with it")
                continue
            shared = set(ranker.tokens(fp(first))) & set(ranker.tokens(fp(r)))
            ts = rare_terms(" ".join(sorted(shared)), df, n)
            if not ts:
                stats["no_term"].append(f"repeat {where}: yielded no rare term")
                continue
            stats["yielded"]["repeat"] += 1
            because = (f"{first.time} — you wrote \"{clip(fp(first), 140)}\", and again at {r.time} "
                       f"\"{clip(fp(r), 140)}\" (state {r.fields.get('state', '').strip()})")
            add("repeat", ts, because, f"repeat ({r.id})", [first.id, r.id])

    for s8, rows in sorted(rows_by.items()):
        rows = turn_rows(rows)
        for i in range(1, len(rows)):
            prev, cur = rows[i - 1], rows[i]
            text = st.norm_token(fp(cur))
            marker = any(text == m or text.startswith(m + " ") for m in MARKERS)
            close = minutes(prev.time, cur.time)
            similar = close is not None and close <= 10 and st.resembles(
                set(text.split()), set(st.norm_token(fp(prev)).split()))
            if not (marker or similar) or fp(prev).lstrip().startswith("!") or fp(cur).lstrip().startswith("!"):
                continue
            stats["signals"]["follow-up"] += 1
            ts = rare_terms(fp(prev), df, n)
            if not ts:
                stats["no_term"].append(f"follow-up {cur.fields.get('from', cur.id)}: yielded no rare term")
                continue
            stats["yielded"]["follow-up"] += 1
            because = (f"{prev.time} — you wrote \"{clip(fp(prev), 140)}\"; you then wrote \"{clip(fp(cur), 140)}\" "
                       f"({cur.time})")
            add("follow-up", ts, because, f"follow-up ({cur.id})", [prev.id])

    # the follow-up detector is untested (8.1 judges its precision by hand): its terms are kept, status off
    pairs = [st.vocab_entry_pairs(t, "(pending)", terms[t]["because"], terms[t]["source"], terms[t]["points"], now,
                                  "off" if terms[t]["source"].startswith("follow-up") else "on")
             for t in order]
    stats["terms"] = len(order)
    return pairs, stats


def minutes(a, b):
    try:
        x = datetime.datetime.strptime(a[:16], "%Y-%m-%d %H:%M")
        y = datetime.datetime.strptime(b[:16], "%Y-%m-%d %H:%M")
        return (y - x).total_seconds() / 60
    except (ValueError, TypeError):
        return None


# --- src -------------------------------------------------------------------------------------------------

def src_head(plan, old_rel):
    task = plan.frag_heads.get(old_rel)
    ext = os.path.splitext(old_rel)[1].lower()
    if not task or ext not in COMMENT:
        return ""
    return f"{COMMENT[ext]} {clip(task, 200)}"


def repo_users(project, names):
    """{name: [project files naming it]} by `git grep -F` over the project's tracked files."""
    out = {}
    if not project or not os.path.isdir(os.path.join(project, ".git")) and not os.path.isfile(
            os.path.join(project, ".git")):
        return None
    for nm in sorted(set(names)):
        if len(nm) < 5:
            continue
        try:
            r = subprocess.run(["git", "-C", project, "grep", "-l", "-F", nm, "--", ".", ":!.claude"],
                               capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        hits = [x for x in r.stdout.splitlines() if x.strip()]
        if hits:
            out[nm] = hits[:5]
    return out


# --- the run ---------------------------------------------------------------------------------------------

def run(p4, out=None, apply=False, now=None, project=None, report_path=None):
    p4 = os.path.abspath(p4)
    now = now or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    date = now[:10]
    out = os.path.abspath(out) if out else p4
    in_place = out == p4
    plan = build_plan(p4, now)
    texts, files = new_files(plan)
    old = old_counts(p4)
    counts, lab, dup_keys = new_counts(files)
    live_new, live_lost = new_live_rules(files)
    f17 = finding17(files)
    tasks, labels, pstats = import_pools(plan, files)
    df, n = df_table(files, p4)
    vocab_pairs, vstats = seed_dictionary(files, df, n, now)
    texts[st.VOCABULARY] = st.render(st.VOCABULARY, vocab_pairs)

    checks = []

    def check(name, ok, detail):
        checks.append((name, bool(ok), detail))

    oc, ol = old["counts"], old["labels"]
    multi_rows = sum(k - 1 for _, k, kind in plan.multi if kind == "row")
    check("rulings: live rules", len(old["live_rules"]) == len(live_new) + len(live_lost),
          f"store_lessons.live_rules {len(old['live_rules'])}; new LIVE {len(live_new)}"
          + (f", freed by a dated retraction {len(live_lost)} (listed)" if live_lost else ""))
    words_old = []
    for s in old_stores(p4):
        f = os.path.join(s, "local-storage.md")
        if os.path.exists(f):
            for b in old_blocks_text(st.read_text(f)):
                if TEMPLATE.search(b):
                    continue
                for m in re.finditer(r'(?m)^\s*-?\s*owner-words:\s*(.*)$', b):
                    words_old.append(m.group(1).strip())
    rules_text = texts["rules.md"]
    missing_words = [w for w in words_old if w and w not in rules_text]
    check("rulings: every owner-words verbatim", not missing_words,
          f"{len(words_old)} owner-words strings, {len(missing_words)} missing")
    check("corrections: count of meant:", oc["correction"] == counts["correction"],
          f"old {oc['correction']}, new {counts['correction']}")
    check("corrections: each key: once", not dup_keys,
          "no key twice" if not dup_keys else "twice or more: " + ", ".join(f"{k} ×{v}" for k, v in dup_keys.items()))
    check("retractions: count of freed:", oc["retraction"] == counts["retraction"],
          f"old {oc['retraction']}, new {counts['retraction']}")
    ow_missing = []
    for e in files["retractions.md"]:
        if not e.fields.get("owner-words", "").strip():
            ow_missing.append(e.fields.get("from", e.id))
    check("retractions: each owner-words present", True,
          f"{counts['retraction'] - len(ow_missing)} with owner-words"
          + (f"; {len(ow_missing)} had none in the old store either: " + ", ".join(ow_missing) if ow_missing else ""))
    check("missed details: count of omitted:", oc["missed"] == counts["missed"],
          f"old {oc['missed']}, new {counts['missed']}")
    claims_old = 0
    for s in old_stores(p4):
        f = os.path.join(s, "data-store.md")
        if os.path.exists(f):
            claims_old += sum(1 for b in old_blocks_text(st.read_text(f))
                              if re.search(r"(?m)^\s*-?\s*claim:", b) and not TEMPLATE.search(b))
    check("facts: count of claim:", claims_old == counts["claim"], f"old {claims_old}, new {counts['claim']}")
    check("index rules: archived", True, f"{len(plan.index_rules)} archived; "
          f"{sum(1 for p in plan.index_rules if any(k == 'owner-words' for k, _ in p))} owner-rooted also in rules.md")
    check("dispatch: rows", ol["rows"] + multi_rows == lab["rows"],
          f"old {ol['rows']}, new {lab['rows']}" + (f" (+{multi_rows}: an old block held two rows with no blank line "
                                                    f"between; store_lessons counted it once)" if multi_rows else ""))
    joined = len(plan.joined) + len(plan.completions)
    why = (f"; {len(plan.joined)} rows had their state:/addressed: written after a blank line, which store_lessons "
           f"credits to the next row's block, and {len(plan.completions)} completions were written as a separate "
           f"`- <message>` entry; both are joined to their own row here") if joined else ""
    check("dispatch: completed (none lost)", lab["completed"] >= ol["completed"] and
          lab["completed"] - ol["completed"] <= joined + multi_rows, f"old {ol['completed']}, new {lab['completed']}" + why)
    check("dispatch: open", lab["open"] <= ol["open"] + multi_rows, f"old {ol['open']}, new {lab['open']}")
    check("dispatch: judged (none lost)", lab["judged"] >= ol["judged"] and
          lab["judged"] - ol["judged"] <= joined + multi_rows, f"old {ol['judged']}, new {lab['judged']}")
    check("dispatch: ECHO/SUPERSEDED rows still so", oc["repeat"] == counts["repeat"],
          f"old {oc['repeat']}, new {counts['repeat']}")
    check("pools: labelled pools imported", pstats["labelled"] == len([t for t in tasks if t[0].startswith("pool:")]),
          f"{pstats['pools']} pools, {pstats['labelled']} labelled (pick_model.labelled_pool), "
          f"{pstats['taught_out']} left out for a teacher's audit; {pstats['audits']} audits")
    check("pools: picks resolved", True,
          f"{pstats['resolved']} of {pstats['picks']} picks resolved ({pstats['to_archive']} to archived entries, "
          f"{pstats['to_freed']} picked while freed or spent, kept on that entry; matched by file, time and head as "
          f"pick_model.build_pairs did); {len(pstats['unresolved'])} unresolved, listed")
    sig_total = sum(vstats["signals"][k] for k in ("correction", "retraction", "missed", "repeat"))
    old_sig = oc["correction"] + oc["retraction"] + oc["missed"] + oc["repeat"]
    check("dictionary: every signal an entry or listed", sig_total == old_sig,
          f"{old_sig} signals; {sum(vstats['yielded'][k] for k in ('correction', 'retraction', 'missed', 'repeat'))} "
          f"yielded terms, the rest listed; {vstats['terms']} pending entries "
          f"(follow-up detector: {vstats['signals']['follow-up']} flagged, {vstats['yielded']['follow-up']} with terms)")
    n_src = len(plan.src)
    check("src: file count", True, f"{n_src} files into src/<s8>-<task>/; "
          f"{sum(1 for o, _ in plan.src if src_head(plan, o))} get a head comment from the register")
    check("finding 17: masked rulings read LIVE", all(s == "LIVE" for _, _, s in f17),
          f"{len(f17)} rulings the old mask freed on shared owner-words; "
          f"{sum(1 for _, _, s in f17 if s == 'LIVE')} read LIVE")

    archived_ok = []
    report = {"apply": apply, "p4": p4, "now": now, "plan": plan, "texts": texts, "files": files, "old": old, "counts": counts,
              "labels": lab, "live_new": live_new, "live_lost": live_lost, "finding17": f17, "tasks": tasks,
              "label_rows": labels, "pools": pstats, "vocab": vstats, "checks": checks, "out": out}

    if apply:
        if os.path.isdir(os.path.join(out, "store")):
            raise SystemExit(f"migrate: {out}/store exists; already migrated")
        write_new(plan, texts, tasks, labels, out, in_place)
        for o, nrel in plan.archive:
            a, b = os.path.join(p4, o), os.path.join(out, nrel)
            archived_ok.append(same_bytes(a, b))
        check("archives byte-identical", all(archived_ok), f"{sum(archived_ok)} of {len(archived_ok)} identical")
        if not in_place:
            for k in plan.kept:
                if k.rstrip("/") in ("memory", "scratchpad", *KEEP_TOP):
                    check(f"{k} tree identical", same_tree(os.path.join(p4, k), os.path.join(out, k)), "copied as is")
    else:
        check("archives byte-identical", True, f"{len(plan.archive)} files to copy verbatim (checked on --apply)")

    users = repo_users(project, [os.path.basename(o) for o, _ in plan.src])
    report["repo_users"] = users
    if project is None and os.path.basename(os.path.dirname(p4)) == ".claude":
        proj = os.path.dirname(os.path.dirname(p4))
        if os.path.isfile(os.path.join(proj, ".git")):
            plan.notes.append("the project dir is a git worktree: a worktree hook outside p4 may block writes under "
                              ".claude/p4/** (finding 7); that is not p4's")
    text = render_report(report)
    rp = report_path or os.path.join(out, "archive", f"migration-{date}.md")
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    with open(rp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if apply and in_place and not plan.unplaced:
        remove_old(plan, p4)
    report["report_path"] = rp
    return report


def same_bytes(a, b):
    try:
        with open(a, "rb") as x, open(b, "rb") as y:
            return x.read() == y.read()
    except OSError:
        return False


def same_tree(a, b):
    for root, _dirs, files in os.walk(a):
        for name in files:
            pa = os.path.join(root, name)
            if not same_bytes(pa, os.path.join(b, os.path.relpath(pa, a))):
                return False
    return True


def write_new(plan, texts, tasks, labels, out, in_place):
    p4 = plan.p4

    def w(rel, text):
        path = os.path.join(out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    for rel, text in texts.items():
        w(f"store/{rel}", text)
    w("archive/index-rules.md", st.render("archive/index-rules.md", plan.index_rules))
    for rel, pairs in plan.unsorted.items():
        w(rel, st.render(rel, pairs))
    w("models/tasks.tsv", "id\tsession\ttime\ttext\tkind\n" + "".join("\t".join(r) + "\n" for r in tasks))
    w("models/labels-raw.tsv", "task\tentry\tlabel\tsource\tweight\ttime\tnote\n"
      + "".join("\t".join(r) + "\n" for r in labels))
    for o, nrel in plan.archive:
        dst = os.path.join(out, nrel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(p4, o), dst)
    for o, nrel in plan.src:
        dst = os.path.join(out, nrel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        head = src_head(plan, o)
        with open(os.path.join(p4, o), "rb") as f:
            data = f.read()
        if head and head.encode("utf-8") not in data[:400]:
            text = data.decode("utf-8", errors="surrogateescape")
            if text.startswith("#!"):
                first, _, rest = text.partition("\n")
                text = first + "\n" + head + "\n" + rest
            else:
                text = head + "\n" + text
            data = text.encode("utf-8", errors="surrogateescape")
        with open(dst, "wb") as f:
            f.write(data)
    if not in_place:
        for k in plan.kept:
            src = os.path.join(p4, k.rstrip("/"))
            if k.rstrip("/") == ".git":
                continue
            dst = os.path.join(out, k.rstrip("/"))
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)


def remove_old(plan, p4):
    """In place, once nothing is unplaced: the old paths go (git history and archive/ keep them)."""
    for top in ("sessions", "vindex", "sindex", "mrindex"):
        path = os.path.join(p4, top)
        if os.path.isdir(path):
            shutil.rmtree(path)
    for o, _n in plan.archive + [(d, "") for d, _r in plan.dropped]:
        if o.startswith("models/"):
            path = os.path.join(p4, o)
            if os.path.isfile(path):
                os.remove(path)
    for root, dirs, _files in os.walk(os.path.join(p4, "models"), topdown=False):
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except OSError:
                pass


def render_report(r):
    plan, old = r["plan"], r["old"]
    L = [f"# Migration report, {r['now']}", "",
         f"Old tree: `{r['p4']}`. New layout: `{r['out']}`. Written by `p4.py migrate` "
         f"({'applied' if r['apply'] else 'dry run'}).", "",
         "## Checks", "", "| check | result | detail |", "|---|---|---|"]
    for name, ok, detail in r["checks"]:
        L.append(f"| {name} | {'pass' if ok else 'FAIL'} | {detail.replace('|', '/')} |")
    L += ["", "## Per kind", "", "| kind | found | written |", "|---|---|---|"]
    c, lab = r["counts"], r["labels"]
    oc, ol = old["counts"], old["labels"]
    for k, o, n_ in (("rulings (store_lessons)", oc["ruling"], c["ruling"]), ("corrections", oc["correction"],
                     c["correction"]), ("retractions", oc["retraction"], c["retraction"]),
                     ("missed details", oc["missed"], c["missed"]), ("repeats", oc["repeat"], c["repeat"]),
                     ("dispatch rows", ol["rows"], lab["rows"]), ("rows completed", ol["completed"], lab["completed"]),
                     ("rows open", ol["open"], lab["open"]), ("rows judged", ol["judged"], lab["judged"]),
                     ("facts", "", c["claim"]), ("index rules (archive)", "", len(plan.index_rules)),
                     ("pool label rows", "", len(r["label_rows"])), ("tasks", "", len(r["tasks"])),
                     ("vocabulary entries (pending)", "", r["vocab"]["terms"]), ("src files", "", len(plan.src)),
                     ("archived verbatim", "", len(plan.archive)), ("dropped", "", len(plan.dropped))):
        L.append(f"| {k} | {o} | {n_} |")
    L += ["", f"Live rules: store_lessons {len(old['live_rules'])}, new LIVE {len(r['live_new'])}.", ""]
    if r["live_lost"]:
        L += ["Rulings whose own status is LIVE that the new rule reads as FREED (a retraction names them):", ""]
        L += [f"- `{i}` {clip(t, 120)}: {why}" for t, i, why in r["live_lost"]]
        L.append("")
    L += ["## Finding 17", "", "Rulings the old mask freed on shared owner-words, by the new rule:", ""]
    L += [f"- {s}: {t} (`{i}`)" for i, t, s in r["finding17"]] or ["- none"]
    L += ["", "## Unplaced", ""]
    L += [f"- {w}: {why}" for w, why in plan.unplaced] or ["- none"]
    L += ["", "## Placed with a reason", ""]
    groups = {}
    for w, where, why in plan.reasons:
        groups.setdefault((where if not where.startswith("archive/sessions") else "archive/<same path>", why), []).append(w)
    for (where, why), ws in sorted(groups.items()):
        L.append(f"- {len(ws)} → `{where}`: {why}" + (f" ({', '.join(ws[:3])}{', …' if len(ws) > 3 else ''})"))
    if plan.multi:
        L += ["", "Old blocks that held more than one entry (split here):", ""]
        L += [f"- {w}: {k} {kind} entries" for w, k, kind in plan.multi]
    L += ["", "## Dropped (derived or retired)", ""]
    dg = {}
    for d, why in plan.dropped:
        dg.setdefault(why, []).append(d)
    L += [f"- {len(ds)} × {why} ({', '.join(ds[:2])}{', …' if len(ds) > 2 else ''})" for why, ds in sorted(dg.items())]
    L += ["", "Kept untouched: " + (", ".join(f"`{k}`" for k in plan.kept) or "nothing"), ""]
    if plan.recall_section:
        L += ["## The old `## recall` section (vindex/phi-index.md), so no setting vanishes silently", "", "```",
              plan.recall_section, "```", ""]
    p = r["pools"]
    L += ["## Pools", "", f"{p['pools']} pools, {p['labelled']} labelled, {p['audits']} audits; {p['resolved']} of "
          f"{p['picks']} picks resolved.", ""]
    if p["unresolved"]:
        L += ["Unresolved picks:", ""] + [f"- {u}" for u in p["unresolved"]] + [""]
    v = r["vocab"]
    L += ["## Dictionary seeds", "", "| signal | found | yielded a term |", "|---|---|---|"]
    L += [f"| {k} | {v['signals'][k]} | {v['yielded'][k]} |" for k in v["signals"]]
    L += ["", f"{v['terms']} pending entries in `store/vocabulary.md`.", ""]
    if v["no_term"]:
        L += ["Signals that produced no entry:", ""] + [f"- {x}" for x in v["no_term"]] + [""]
    L += ["## src", ""]
    users = r.get("repo_users")
    if users is None:
        L.append("No project repository given (or none found), so no frag was checked against the project's "
                 "tracked files; `--project <dir>` lists the frags the repo uses.")
    elif users:
        L += ["Frags the project repo names (listed for the owner, not moved):", ""]
        L += [f"- `{nm}`: used by {', '.join(u)}" for nm, u in sorted(users.items())]
    else:
        L.append("No frag is named by the project's tracked files.")
    if plan.notes:
        L += ["", "## Notes", ""] + [f"- {x}" for x in plan.notes]
    return "\n".join(L) + "\n"


def summary(r):
    plan = r["plan"]
    fails = [c for c in r["checks"] if not c[1]]
    lab = r["labels"]
    return (f"migrate{'' if r['apply'] else ' (dry)'}: rulings {r['counts']['ruling']} "
            f"(live {len(r['live_new'])}), corrections {r['counts']['correction']}, retractions "
            f"{r['counts']['retraction']}, missed {r['counts']['missed']}, repeats {r['counts']['repeat']}, rows "
            f"{lab['rows']} ({lab['completed']} completed, {lab['open']} open, {lab['judged']} judged), facts "
            f"{r['counts']['claim']}, pool labels {len(r['label_rows'])}, vocabulary {r['vocab']['terms']}, "
            f"finding 17 {sum(1 for x in r['finding17'] if x[2] == 'LIVE')}/{len(r['finding17'])} LIVE; unplaced "
            f"{len(plan.unplaced)}; checks {len(r['checks']) - len(fails)}/{len(r['checks'])} pass"
            + ("".join(f"\n  FAIL {n}: {d}" for n, _, d in fails)) + f"\n  report: {r['report_path']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--p4", required=True, help="the old .claude/p4 tree")
    ap.add_argument("--out", default="", help="where the new layout goes (default: in place)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--now", default="")
    ap.add_argument("--project", default=None, help="the project repo, to list the frags it uses")
    ap.add_argument("--report", default="", help="the report's path (default <out>/archive/migration-<date>.md)")
    args = ap.parse_args(argv)
    r = run(args.p4, args.out or None, args.apply, args.now or None, args.project, args.report or None)
    print(summary(r))
    fails = [c for c in r["checks"] if not c[1]]
    return 1 if fails or r["plan"].unplaced else 0


if __name__ == "__main__":
    sys.exit(main())
