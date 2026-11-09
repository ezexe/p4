#!/usr/bin/env python3
"""store.py: the files under `.claude/p4/store/`, their entries and ids, the status rule, the vocabulary
dictionary, and the derived `models/index.json` that recall reads.

The store format (fresh-marketplace.md 3.5, 4.2): Markdown files of dash-led entries, one field per line, a blank
line between entries; each file starts with three lines in ordinary words. Field names are the old store's
(`ruling:`, `match:`, `meant:`, `freed:`, `state:`, `addressed:`). A value that spans lines continues on lines
indented four spaces.

    - ruling: the macOS deployment target is 13.3
      owner-words: "Raise to 13.3"
      status: LIVE
      time: 2026-11-01 10:50

An entry's id is `<file>:<time>:<sha8 of its first field's text>` (file relative to store/, e.g. `rules.md` or
`messages/150e7eb7.md`), so it stays the same when lines move; a second entry with the same id in one file gets
`~2`, and so on.

The status rule (finding 17, the held branch's fix): an entry is FREED only by a retraction whose `freed:` head
matches it (one contained in the other, the shorter side at least 24 characters), or by owner-words shared with a
retraction dated after the entry; `SPENT` (and an explicit `FREED` or `EXPIRED`) is the entry's own field, never
inferred. Retractions themselves are never freed.
"""

import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ranker  # noqa: E402

STORE_FILES = ("rules.md", "corrections.md", "retractions.md", "facts.md")
VOCABULARY = "vocabulary.md"
MESSAGES = "messages"
INDEX_VERSION = 6
MASK_MIN = 24
SHORT_WORDS = 5
KNOWN_SHORT_MIN = 2
BARRIER_JACCARD = 0.5
BARRIER_MIN_TOKENS = 3

HEADERS = {
    "rules.md": ("The owner's rulings: what holds past the turn, in the owner's own words.",
                 "Written when the owner rules something; a later retraction frees a ruling, never an edit here.",
                 "Fields: ruling, owner-words, scope, form, status, time, pinned, plain."),
    "corrections.md": ("Readings that steered work and were wrong, and details the owner had to ask for.",
                       "Written when the owner corrects a reading (match, meant) or asks for what was left out "
                       "(asked, omitted).",
                       "Fields: key, time, match, meant, delta; asked, time, omitted."),
    "retractions.md": ("What the owner freed: a rule or reading no longer in force, and the lesson kept from it.",
                       "Written when the owner takes something back; recall shows these in place of what they freed.",
                       "Fields: freed, time, cause, owner-words, swept, lesson."),
    "facts.md": ("Claims checked against a source, with where and when they were checked.",
                 "Written when a claim is verified; a claim without a source stays out.",
                 "Fields: claim, source, verified, time."),
    VOCABULARY: ("The owner's words that were once misread, what they mean, and the exchange that proves it.",
                 "Grown from corrections, retractions, missed details and repeats; the owner edits it freely.",
                 "Fields: term, means, because, source, points-at, added, status (on or off)."),
    MESSAGES: ("Every owner message of one session: when it came, how it arrived, and what was done about it.",
               "Opened by the prompt hook and completed by the close hook from the reply.",
               "Fields: fingerprint, time, arrival, state, addressed, recommended, match, freed-by, resembles."),
}

# what each file prints as at the boundary (3.5): plain words, never the file's name
KIND_NAMES = {"rules.md": "rule", "corrections.md": "correction", "retractions.md": "retracted", "facts.md": "fact",
              "memory": "memory", "messages": "earlier message", VOCABULARY: "your word", "src": "saved code"}

# the suite's jargon list (scripts/session/overrides_suite.py JARGON): a printed line must hold none of these
JARGON = re.compile(r"(?i)\b(frags?|rulings?|pour(ed|s)?|tombstones?|derivations?|the operator|register entry|"
                    r"read barrier|write barrier|dispatch row|hot tier|cold tier|pre-finalizers?|vlds|phi-index)\b(?!-)")

# words too ordinary to be a term of the owner's own: never a dictionary term, never a rare term that makes a line
COMMON = frozenset("""able about above actually add added again ago agree ahead also always another answer anything
anyway around asked back because before being better big bit both build built call came case change changed check
clean code come coming correct could current day did different does doing done down each else end enough even
ever everything exactly fail failed file files find fine first fix fixed following found full get getting give go
goes going gone good got great had happen happened hard has have help here high hold how idea instead just keep
kind know last later least left let like line little long look looking looks lot make makes making many maybe mean
means meant might mine more most move moved much must name need needed needs new next nice none now number off okay
old once only open other over part pass path please point possible pretty probably problem put quick quite rather
read ready real really reason right run running said same say says second see seems seen set should show side since
small some something soon sorry start started still stop sure take taken talk tell test tested tests than thank
thanks that the them then there these thing things think this those though thought through time today told too
took top tried try trying turn under until update updated use used using want wanted wants way well went were what
when where whether which while why will with without work worked working works would wrong yeah yes yet you your
ok lets dont didnt doesnt isnt wasnt cant wont youre thats whats heres theres ive youve
accept across act action actual add adding address after afternoon against all allow almost alone along already
alright also although among amount another anyone anyway anywhere apply area ask asking away bad based basic become
began begin behind believe below best between beyond both bring broke broken brought business busy came cannot
care carry cause certain chance clear clearly close closed coming common complete completely consider continue copy
cost couple course create created cut date days deal decide decided deep define delete describe detail details die
directly doing door double doubt down draft during early easy edit either else empty entire error especially event
example except expect explain fact fair far fast feel few field fill final finally finish finished follow form
forward free front general given goes gone group guess half hand handle happy head hear held hello hey hi hit home
hope hour hours house however huge include including inside issue item items itself job join keep kept key knew
large late later learn leave less level life light likely limit list listed live load local locally lose loss lost
love low main major makes manage mark matter mind minute minutes miss missing mode moment month morning move much
myself near nearly necessary never night normal note notes nothing notice often okay once open order original
others otherwise outside page paper part past pay people perhaps person pick place plan play plus present press
previous print private process product proper pull push quickly raise ran range rate reach reading reasons recent
record remember remove removed reply report request rest result return review room round rule safe save saw search
seem select send sense sent separate serious short shot shown simple simply single sit size slow somehow someone
somewhere sort sound source space speak specific spot stand state stay step stuff such suggest support suppose
system table taking task team term text thinking third three thus together total toward tried true truly type
typical understand unless upon usual usually value various version view wait waiting walk week weird whatever whole
wide wish within word words world write writing written wrote year""".split())

HEAD_RE = re.compile(r"^- ([a-z][a-z0-9_-]*):(?: (.*))?$")
FIELD_RE = re.compile(r"^  ([a-z][a-z0-9_-]*):(?: (.*))?$")
CONT_PREFIX = "    "
NOT_TEXT = frozenset(("time", "status", "from", "arrival", "pinned", "added", "id", "session", "points-at",
                      "supersedes", "resembles"))


# --- entries ---------------------------------------------------------------------------------------------

class Entry:
    __slots__ = ("file", "line", "pairs", "fields", "id", "state", "reason")

    def __init__(self, file, line, pairs):
        self.file, self.line, self.pairs = file, line, pairs
        self.fields = {}
        for k, v in pairs:
            self.fields.setdefault(k, v)
        self.id = ""
        self.state, self.reason = "LIVE", ""

    @property
    def head(self):
        return self.pairs[0][0] if self.pairs else ""

    @property
    def value(self):
        return self.pairs[0][1] if self.pairs else ""

    @property
    def time(self):
        return self.fields.get("time", "").strip()

    def all(self, key):
        return [v for k, v in self.pairs if k == key]

    def __repr__(self):
        return f"Entry({self.id!r}, line {self.line})"


def sha8(text):
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:8]


def parse(text, file=""):
    """[Entry] from a store file's text: every column-0 `- key: value` line opens an entry, its two-space field
    lines follow, a four-space line continues the field before it. Anything else (the header prose) is skipped."""
    out, cur = [], None
    for n, l in enumerate(text.split("\n"), 1):
        m = HEAD_RE.match(l)
        if m:
            cur = Entry(file, n, [(m.group(1), m.group(2) or "")])
            out.append(cur)
            continue
        if cur is None:
            continue
        m = FIELD_RE.match(l)
        if m:
            cur.pairs.append((m.group(1), m.group(2) or ""))
            cur.fields.setdefault(m.group(1), m.group(2) or "")
            continue
        if l.startswith(CONT_PREFIX) and cur.pairs:
            k, v = cur.pairs[-1]
            cur.pairs[-1] = (k, v + "\n" + l[len(CONT_PREFIX):])
            if cur.fields.get(k) == v:
                cur.fields[k] = cur.pairs[-1][1]
            continue
        if not l.strip():
            continue
        cur = None                       # prose after an entry ends it
    assign_ids(out, file)
    return out


def assign_ids(entries, file):
    seen = {}
    for e in entries:
        base = f"{file}:{e.time}:{sha8(e.value)}"
        n = seen.get(base, 0) + 1
        seen[base] = n
        e.id = base if n == 1 else f"{base}~{n}"


def format_entry(pairs):
    """The text of one entry: `- head: value`, then `  field: value`, a multi-line value continued four spaces in."""
    lines = []
    for i, (k, v) in enumerate(pairs):
        first, *rest = (v or "").split("\n")
        lead = "- " if i == 0 else "  "
        lines.append(f"{lead}{k}:" + (f" {first}" if first != "" else ""))
        lines += [CONT_PREFIX + r for r in rest]
    return "\n".join(lines)


def render(fname, entries_pairs):
    """A whole store file: its three header lines, a blank line, then the entries a blank line apart."""
    key = MESSAGES if fname.startswith(MESSAGES + "/") else fname
    head = "\n".join(HEADERS.get(key, ("", "", "")))
    body = "\n\n".join(format_entry(p) for p in entries_pairs)
    return head + "\n\n" + body + ("\n" if body else "")


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def store_dir(p4):
    return os.path.join(p4, "store")


def load_file(p4, rel):
    path = os.path.join(store_dir(p4), rel)
    if not os.path.isfile(path):
        return []
    return parse(read_text(path), rel)


def message_files(p4):
    d = os.path.join(store_dir(p4), MESSAGES)
    if not os.path.isdir(d):
        return []
    return sorted(f"{MESSAGES}/{n}" for n in os.listdir(d) if n.endswith(".md"))


def load_store(p4):
    """{file: [Entry]} for the four store files and every messages file, statuses applied."""
    got = {f: load_file(p4, f) for f in STORE_FILES}
    for rel in message_files(p4):
        got[rel] = load_file(p4, rel)
    apply_status(got)
    return got


# --- the status rule -------------------------------------------------------------------------------------

def norm_text(v):
    """A field value normalized for matching: quotes and a trailing ellipsis off, whitespace collapsed, lower case."""
    v = (v or "").strip().strip('"').strip("'").rstrip("…").strip()
    return re.sub(r"\s+", " ", v).lower()


def masks(retractions):
    """[(id, freed, owner-words, time)] for every retraction, normalized."""
    return [(e.id, norm_text(e.fields.get("freed", e.value)), norm_text(e.fields.get("owner-words", "")), e.time)
            for e in retractions]


def mask_hit(value, fields, ms, rule="new"):
    """(retraction id, time, why) for the first retraction that frees an entry, or None.

    rule "new" (3.5): shared owner-words free only an entry dated before the retraction; rule "old" (the masking
    before finding 17's fix) frees on shared owner-words whatever the dates. A head contained in a `freed:` (or the
    reverse), the shorter side at least MASK_MIN characters, frees under both."""
    head, own = norm_text(value), norm_text(fields.get("owner-words", ""))
    stamp = str(fields.get("time", "")).strip()
    for ref, freed, words, when in ms:
        if own and words and own == words:
            if rule == "old" or not (stamp and when and stamp >= str(when).strip()):
                return ref, when, "the same owner-words, before the retraction"
        short, long_ = (head, freed) if len(head) <= len(freed) else (freed, head)
        if len(short) >= MASK_MIN and short in long_:
            return ref, when, "its head within the retraction's freed:"
    return None


def status_of(fname, value, fields, ms, rule="new"):
    own = (fields.get("status") or "").strip().upper().split(" ")[0] if fields.get("status") else ""
    if own in ("SPENT", "FREED", "EXPIRED"):
        return own, "its own status field"
    if fname == "retractions.md" or fname.startswith(MESSAGES + "/"):
        return "LIVE", "never freed"
    hit = mask_hit(value, fields, ms, rule)
    if hit:
        return "FREED", f"freed by {hit[0]} ({hit[1]}): {hit[2]}"
    return "LIVE", "its own status field" if own == "LIVE" else "no status, no retraction"


def apply_status(files, rule="new"):
    ms = masks(files.get("retractions.md", []))
    for fname, entries in files.items():
        for e in entries:
            e.state, e.reason = status_of(fname, e.value, e.fields, ms, rule)


# --- the vocabulary dictionary (5.3) ---------------------------------------------------------------------

def read_vocabulary(p4):
    """[{term, means, because: [..], source, points-at: [ids], added, status, line, pending}] from vocabulary.md."""
    out = []
    for e in load_file(p4, VOCABULARY):
        if e.head != "term":
            continue
        means = e.fields.get("means", "").strip()
        pts = [p.strip() for p in re.split(r",\s+(?=[a-z/]+\.md:)", e.fields.get("points-at", "")) if p.strip()]
        out.append({"term": e.value.strip(), "means": means, "because": e.all("because"),
                    "source": e.fields.get("source", ""), "points-at": pts, "added": e.fields.get("added", ""),
                    "status": (e.fields.get("status", "on").strip().lower() or "on"), "line": e.line,
                    "pending": not means or means.startswith("(pending")})
    return out


def vocab_entry_pairs(term, means, because, source, points_at, added, status="on"):
    pairs = [("term", term), ("means", means)]
    pairs += [("because", b) for b in (because if isinstance(because, list) else [because])]
    pairs += [("source", source), ("points-at", ", ".join(points_at)), ("added", added), ("status", status)]
    return pairs


# --- short turns and resemblance (the old prompt hook's rules) --------------------------------------------

def norm_token(text):
    """The old `_token`: lower-cased, punctuation out, whitespace collapsed."""
    t = (text or "").lower().replace("…", " ").replace("’", "'")
    t = re.sub(r"[^\w\s'/-]", " ", t)
    return " ".join(t.split())


def unquote(v):
    v = (v or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v.strip()


def resembles(new, old):
    """The old barrier's rule over fingerprint token sets: identical, or Jaccard >= 0.5 when the new one has at
    least three tokens."""
    if not new or not old:
        return False
    if new == old:
        return True
    return len(new) >= BARRIER_MIN_TOKENS and len(new & old) / len(new | old) >= BARRIER_JACCARD


NOT_OWNER_ARRIVAL = re.compile(r"(?i)\s*(task notification|notification|agent message|hook injection)")


def owner_message(e, fp=None):
    """A row of the owner's own words: not a notification, an agent's message or a harness injection (`<...>`)."""
    fp = unquote(e.fields.get("fingerprint", e.value)) if fp is None else fp
    return not NOT_OWNER_ARRIVAL.match(e.fields.get("arrival", "")) and not fp.lstrip().startswith("<")


def completed(e):
    return bool(e.fields.get("addressed", "").strip())


# --- what an entry prints as -----------------------------------------------------------------------------

def collapse(s):
    return re.sub(r"\s+", " ", unquote(s or "")).strip()


def kind_of(fname, e=None):
    if fname.startswith(MESSAGES + "/"):
        return KIND_NAMES["messages"]
    if fname == "corrections.md" and e is not None and ("omitted" in e.fields or "asked" in e.fields):
        return "missed detail"
    return KIND_NAMES.get(fname, fname)


def show_text(fname, e):
    """The entry in ordinary words, before the 160-character cut: its `plain:` when it has one."""
    f = e.fields
    if f.get("plain", "").strip():
        return collapse(f["plain"])
    if fname == "corrections.md":
        if "omitted" in f or "asked" in f:
            return collapse(f"you asked \"{unquote(f.get('asked', e.value))}\"; it had left out: {f.get('omitted', '')}")
        meant, match = collapse(f.get("meant", "")), collapse(f.get("match", ""))
        return f"meant {meant}" + (f"; not {match}" if match else "") if meant else collapse(e.value)
    if fname == "retractions.md":
        lesson = collapse(f.get("lesson", ""))
        return collapse(f.get("freed", e.value)) + (f"; now: {lesson}" if lesson else "")
    if fname == MESSAGES or fname.startswith(MESSAGES + "/"):
        return f"\"{collapse(f.get('fingerprint', e.value))}\" was answered: {collapse(f.get('addressed', ''))}"
    return collapse(e.value)


def feature_kind(fname, e):
    """The kind the ranker's `kind=` feature sees, finer than the printed one where the old barrier was: a ruling
    with a `form:` is a form; a fact is sourced or unsourced."""
    if fname == "rules.md":
        return "form" if e.fields.get("form", "").strip() else "rule"
    if fname == "facts.md":
        return "fact sourced" if e.fields.get("verified", "").strip() or e.fields.get("source", "").strip() \
            else "fact unsourced"
    return kind_of(fname, e)


def entry_text(e):
    """The words an entry is indexed by: its head and every field but the bookkeeping ones."""
    return " ".join([e.value] + [v for k, v in e.pairs[1:] if k not in NOT_TEXT])


# --- memory and src entries ------------------------------------------------------------------------------

def stamp_of(path):
    import time as _t
    try:
        return _t.strftime("%Y-%m-%d %H:%M", _t.localtime(os.path.getmtime(path)))
    except OSError:
        return ""


def memory_entries(p4):
    """One entry per heading of every memory/*.md (MEMORY.md, the index of links, aside); a file without headings
    is one entry headed by its frontmatter description or first line."""
    d = os.path.join(p4, "memory")
    out = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md") or name == "MEMORY.md":
            continue
        path = os.path.join(d, name)
        lines = read_text(path).split("\n")
        when = stamp_of(path)
        desc, body_start = "", 0
        if lines and lines[0].strip() == "---":
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    body_start = i + 1
                    break
                m = re.match(r"^(description|name):\s*(.*)$", lines[i])
                if m and (m.group(1) == "description" or not desc):
                    desc = m.group(2).strip()
        pre = [body_start + 1, desc or name[:-3], []]
        sections, cur = [], pre
        for i in range(body_start, len(lines)):
            m = re.match(r"^#{1,6}\s+(.*)$", lines[i])
            if m:
                cur = [i + 1, m.group(1).strip(), []]
                sections.append(cur)
            else:
                cur[2].append(lines[i])
        if any(x.strip() for x in pre[2]) or not sections:
            sections.insert(0, pre)
        rel = f"memory/{name}"
        for line, title, body in sections:
            text = " ".join(x.strip() for x in body if x.strip())
            pairs = [("memory", title), ("text", text[:2000]), ("time", when)]
            e = Entry(rel, line, pairs)
            e.id = f"{rel}::{sha8(title)}"
            out.append(e)
    return out


def src_entries(p4):
    """The one-line head of each file under src/ (its first non-empty line, comment marks off)."""
    d = os.path.join(p4, "src")
    out = []
    if not os.path.isdir(d):
        return out
    for root, dirs, files in os.walk(d):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(root, name)
            rel = "src/" + os.path.relpath(path, d).replace(os.sep, "/")
            try:
                if os.path.getsize(path) > 1 << 20:
                    continue
                with open(path, encoding="utf-8") as f:
                    head = ""
                    for l in f:
                        if l.startswith("#!"):
                            continue
                        if l.strip():
                            head = l.strip()
                            break
            except (OSError, UnicodeDecodeError):
                continue
            head = re.sub(r"^(#+|//+|/\*+|--|;+|<!--|\"\"\"|''')\s*", "", head).strip()
            e = Entry(rel, 1, [("src", f"{rel[4:]}: {head}"[:300]), ("time", stamp_of(path))])
            e.id = f"{rel}::{sha8(rel)}"
            out.append(e)
    return out


# --- the index -------------------------------------------------------------------------------------------

def index_path(p4):
    return os.path.join(p4, "models", "index.json")


def sources_signature(p4):
    """(count, newest mtime_ns) over every file and directory under store/, memory/ and src/ (os.scandir: one stat
    per entry, no path joins, the hot path of every message's staleness check)."""
    count, newest = 0, 0
    try:
        st_ = os.stat(os.path.join(p4, "models", "repo.json"))     # the repository's entries (repo.py)
        count, newest = 1, st_.st_mtime_ns
    except OSError:
        pass
    stack = [os.path.join(p4, sub) for sub in ("store", "memory", "src")]
    while stack:
        top = stack.pop()
        try:
            newest = max(newest, os.stat(top).st_mtime_ns)
            it = os.scandir(top)
        except OSError:
            continue
        with it:
            for ent in it:
                try:
                    if ent.is_dir(follow_symlinks=False):
                        stack.append(ent.path)
                        continue
                    m = ent.stat().st_mtime_ns
                except OSError:
                    continue
                count += 1
                newest = max(newest, m)
    return count, newest


def index_stale(p4):
    """True when models/index.json is missing, of another version, or older than a store, memory or src file (or
    the file count moved: a deletion)."""
    path = index_path(p4)
    try:
        st = os.stat(path)
        with open(path, encoding="utf-8") as f:
            head = f.read(200)
    except OSError:
        return True
    m = re.search(r'"version":\s*(\d+).*?"sources":\s*\[(\d+),\s*(\d+)\]', head, re.S)
    if not m or int(m.group(1)) != INDEX_VERSION:
        return True
    count, newest = sources_signature(p4)
    return count != int(m.group(2)) or newest > st.st_mtime_ns or newest != int(m.group(3))


def display_path(e):
    return (f"store/{e.file}" if not e.file.startswith(("memory/", "src/")) else e.file)


def make_doc(e, fname, kind):
    """One index doc for an entry, its term frequencies under `_tf` (turned into postings by build_index)."""
    toks = ranker.tokens(entry_text(e))
    head = ranker.tokens(e.value[:400])
    tf = {}
    for t in toks:
        tf[t] = tf.get(t, 0) + 1
    return {"id": e.id, "path": display_path(e), "line": e.line, "file": fname, "kind": kind,
            "time": e.time, "state": e.state, "show": show_text(fname, e)[:240],
            "plain": bool(e.fields.get("plain", "").strip()), "dl": len(toks), "_tf": tf,
            "toks": " ".join(tf), "head": " ".join(dict.fromkeys(head)),
            **({"match": collapse(e.fields.get("match", ""))[:300]} if fname == "corrections.md" else {}),
            **({"supersedes": e.fields["supersedes"].strip()} if e.fields.get("supersedes", "").strip()
               else {}),
            **({"fkind": feature_kind(fname, e)} if feature_kind(fname, e) != kind else {})}


def held_docs(p4, files=None):
    """The store entries the index leaves out (FREED, SPENT, EXPIRED) as docs with their `_tf`: never recalled, but
    an old pool's reader saw them on the barrier with their state and could pick one, so train.py keeps them among
    a pool task's candidates, as pick_model.py's barrier rows did."""
    files = files if files is not None else load_store(p4)
    return [make_doc(e, fname, kind_of(fname, e)) for fname in STORE_FILES for e in files.get(fname, [])
            if e.state != "LIVE"]


def build_index(p4, write=True):
    """The index recall reads: every LIVE entry of the store files, every completed message row, every memory
    section and every src head, tokenized, with BM25's postings; plus the short-turn table, each session's rows
    for the repeat line, and the vocabulary for expansion."""
    files = load_store(p4)
    docs, excluded = [], {}
    session_rows, short = {}, {}

    def add(e, fname, kind):
        docs.append(make_doc(e, fname, kind))

    for fname in STORE_FILES:
        for e in files.get(fname, []):
            if e.state != "LIVE":
                excluded[e.state] = excluded.get(e.state, 0) + 1
                continue
            add(e, fname, kind_of(fname, e))
    for rel in sorted(k for k in files if k.startswith(MESSAGES + "/")):
        s8 = rel[len(MESSAGES) + 1:-3]
        rows = session_rows.setdefault(s8, [])
        for e in files[rel]:
            fp = unquote(e.fields.get("fingerprint", e.value))
            if not owner_message(e, fp):
                # a notification, an agent's message or a harness injection is not the owner speaking: never a line,
                # never a short turn or a repeat
                excluded["not the owner's"] = excluded.get("not the owner's", 0) + 1
                continue
            tok = norm_token(fp)
            done = completed(e)
            addressed = collapse(e.fields.get("addressed", ""))
            rows.append([e.time, tok[:300], 1 if done else 0, addressed[:160]])
            if tok and len(tok.split()) <= SHORT_WORDS:
                short.setdefault(tok, []).append([e.time, s8, 1 if done else 0, addressed[:300], "store/" + rel,
                                                  e.line])
            if done:
                add(e, "messages", KIND_NAMES["messages"])
            else:
                excluded["open row"] = excluded.get("open row", 0) + 1
    for e in memory_entries(p4):
        add(e, "memory", KIND_NAMES["memory"])
    for e in src_entries(p4):
        add(e, "src", KIND_NAMES["src"])
    for d in repo_docs(p4):
        toks = ranker.tokens(d["text"])
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        docs.append({"id": d["id"], "path": d["path"], "line": d["line"], "file": d["kind"] if d["kind"] == "commit"
                     else "repo", "kind": d["kind"], "time": d["time"], "state": "LIVE", "show": d["show"][:400],
                     "plain": True, "dl": len(toks), "_tf": tf, "toks": " ".join(tf),
                     "head": " ".join(dict.fromkeys(ranker.tokens(d["head"][:400])))})
    for v in short.values():
        v.sort(key=lambda r: (r[0], r[1], r[5]))
    post, df, total = {}, {}, 0
    for i, d in enumerate(docs):
        total += d["dl"]
        for t, c in d.pop("_tf").items():
            post.setdefault(t, []).extend((i, c))
            df[t] = df.get(t, 0) + 1
    vocab = []
    for v in read_vocabulary(p4):
        vocab.append({**v, "term_toks": ranker.tokens(v["term"]), "means_toks": ranker.tokens(v["means"])
                      if not v["pending"] else [], "norm": norm_token(v["term"])})
    sig = sources_signature(p4)
    out = {"version": INDEX_VERSION, "sources": list(sig), "n": len(docs),
           "avgdl": (total / len(docs)) if docs else 1.0, "excluded": excluded, "docs": docs, "post": post,
           "short": short, "sessions": session_rows, "vocab": vocab, "stems": ranker.stem_table(post),
           # what a query reads of every doc, kept apart so a query never decodes all of them (load_index's Docs)
           "dl": [d["dl"] for d in docs],
           "sup": [[d.get("time") or "", d["supersedes"]] for d in docs if d.get("supersedes")],
           "rule_at": rule_minutes(docs)}
    if write:
        # on disk the docs are rows and the postings strings, decoded only for a query's terms: half the load time
        disk = dict(out)
        disk["doc_fields"] = list(DOC_FIELDS)
        disk["docs"] = [[d.get(k) for k in DOC_FIELDS] for d in docs]
        disk["post"] = {t: " ".join(map(str, v)) for t, v in post.items()}
        text = json.dumps(disk, separators=(",", ":"), ensure_ascii=False)
        ranker.write_atomic(index_path(p4), text)
        write_cache(p4, disk)          # the next message's load is warm (load_index)
    return out


DOC_FIELDS = ("id", "path", "line", "file", "kind", "time", "state", "show", "plain", "dl", "toks", "head", "match",
              "supersedes", "fkind")


def repo_docs(p4):
    """The repository's entries (4.1a) from models/repo.json, when `p4.py index --repo` has run."""
    try:
        import repo
    except ImportError:
        return []
    try:
        return repo.entries(p4)
    except (OSError, ValueError, KeyError):
        return []


def cache_path(p4):
    # named under the seeded .gitignore's `models/*.tmp`, so a store seeded before the cache existed ignores it too
    return os.path.join(p4, "models", "index-cache.tmp")


def load_index(p4):
    """The index as build_index wrote it, its docs as dicts. A hook is a new process every message, so the decoded
    index is kept beside the JSON in models/index-cache.tmp (marshal: about a third of json.load's time on
    AudioPlugin-p4), keyed on the JSON's mtime and size; a cache that does not match, or does not read, is rebuilt
    from the JSON and written again."""
    import marshal
    path = index_path(p4)
    s = os.stat(path)
    key = [s.st_mtime_ns, s.st_size, INDEX_VERSION]
    idx = None
    try:
        with open(cache_path(p4), "rb") as f:
            got = marshal.loads(f.read())
        if isinstance(got, dict) and got.get("_key") == key:
            idx = got
    except (OSError, EOFError, ValueError, TypeError):
        idx = None
    if idx is None:
        with open(path, encoding="utf-8") as f:
            idx = json.load(f)
        write_cache(p4, idx)
    idx.pop("_key", None)
    fields = idx.pop("doc_fields", None)
    if fields:
        idx["docs"] = Docs(idx["docs"], fields)
    return idx


def write_cache(p4, disk):
    """models/index-cache.tmp: the on-disk index (rows, posting strings) in marshal, keyed on index.json's mtime
    and size; best effort."""
    import marshal
    try:
        s = os.stat(index_path(p4))
        tmp = cache_path(p4) + f".{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            f.write(marshal.dumps({**disk, "_key": [s.st_mtime_ns, s.st_size, INDEX_VERSION]}))
        os.replace(tmp, cache_path(p4))
    except (OSError, ValueError):
        pass


class Docs:
    """The index's docs, each decoded from its on-disk row into a dict the first time it is read: a query reads a
    few hundred of AudioPlugin-p4's 5,000, so the rest are never built."""
    __slots__ = ("rows", "fields", "got")

    def __init__(self, rows, fields):
        self.rows, self.fields, self.got = rows, tuple(fields), [None] * len(rows)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self[k] for k in range(*i.indices(len(self.rows)))]
        d = self.got[i]
        if d is None:
            d = self.got[i] = dict(zip(self.fields, self.rows[i]))
        return d

    def __iter__(self):
        for i in range(len(self.rows)):
            yield self[i]


def rule_minutes(docs):
    """{minute: [doc index]} of the rulings, by the minute they were written (p4.standing_first)."""
    out = {}
    for i, d in enumerate(docs):
        if d["file"] == "rules.md" and d.get("time"):
            out.setdefault(d["time"][:16], []).append(i)
    return out


def postings(idx, term):
    """[doc, tf, doc, tf, ...] for one term (decoded from the on-disk string on first use), or None."""
    p = idx["post"].get(term)
    if isinstance(p, str):
        p = idx["post"][term] = [int(x) for x in p.split()]
    return p


def ensure_index(p4):
    """(index, rebuilt?): the index, rebuilt first when a source is newer."""
    if index_stale(p4):
        return build_index(p4), True
    try:
        return load_index(p4), False
    except (OSError, ValueError):
        return build_index(p4), True


def find_p4(given=None, cwd=None):
    """The .claude/p4 directory: the one given (or its .claude/p4), else CLAUDE_PROJECT_DIR's, else cwd's."""
    for base in (given, os.environ.get("CLAUDE_PROJECT_DIR"), cwd or os.getcwd()):
        if not base:
            continue
        base = os.path.abspath(base)
        if os.path.isdir(os.path.join(base, "store")) or os.path.basename(base) == "p4" and given:
            return base
        cand = os.path.join(base, ".claude", "p4")
        if os.path.isdir(cand):
            return cand
        if given:
            return base
    return None
