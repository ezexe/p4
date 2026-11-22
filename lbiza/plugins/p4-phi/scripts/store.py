#!/usr/bin/env python3
"""store.py: the corpus and its index. The corpus is the entry files under `phi/store/` of the store `.claude/p4`;
this module reads their entries and ids, applies the status rule and reads the vocabulary dictionary. The index
`phi/models/index.json` is what retrieval reads: the documents the ranker scores, built from the corpus, the memory
files, the saved code, the repository and its dependencies.

The corpus is Markdown files of dash-led entries, one field per line and a blank line between entries. Each file
starts with three header lines in ordinary words, which parse skips. A value that spans lines continues on lines
indented four spaces.

    - ruling: the macOS deployment target is 13.3
      owner-words: "Raise to 13.3"
      status: LIVE
      time: 2026-11-01 10:50

An entry's id is `<file>:<time>:<sha8 of its first field's text>`, with the file relative to `phi/store/` as in
`rules.md` or `messages/150e7eb7.md`. The id holds no line number, so it stays the same when lines move; a second
entry with the same id in one file gets `~2`, and so on.

The status rule: an entry's own `status:` of SPENT, FREED or EXPIRED stands, and SPENT is never inferred. Otherwise
a retraction frees the entry in two ways. Its `freed:` text frees the entry when one of that text and the entry's
head contains the other and the shorter is at least MASK_MIN characters long. Its owner-words free the entry when
they equal the entry's, unless both are dated and the entry is no older than the retraction. No retraction frees a
retraction or a message row.
"""

import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import ranker  # noqa: E402

STORE_FILES = ("rules.md", "corrections.md", "retractions.md", "facts.md")
VOCABULARY = "vocabulary.md"
MESSAGES = "messages"
INDEX_VERSION = 7
HEAD_CHARS = 140              # a corpus entry's head: the characters of its value the head-bm25 feature reads
MASK_MIN = 24
SHORT_WORDS = 5
KNOWN_SHORT_MIN = 2
BARRIER_JACCARD = 0.5
BARRIER_MIN_TOKENS = 3

HEADERS = {
    "rules.md": ("ezexe's rulings: what holds past the turn, in ezexe's own words.",
                 "Written when ezexe rules something; a later retraction frees a ruling, never an edit here.",
                 "Fields: ruling, owner-words, scope, form, status, time, plain; a migrated entry adds from."),
    "corrections.md": ("Readings that steered work and were wrong, and details ezexe had to ask for.",
                       "Written when ezexe corrects a reading or asks for what was left out.",
                       "Fields: key, time, match, meant, delta for a corrected reading; asked, time, omitted for a "
                       "missed detail; a migrated entry may also hold correction and from."),
    "retractions.md": ("What ezexe freed: a rule or reading out of force, and the lesson kept from it.",
                       "Written when ezexe takes something back; retrieval shows these in place of what they freed.",
                       "Fields: freed, time, cause, owner-words, swept, lesson; a migrated entry adds from."),
    "facts.md": ("Claims checked against a source, with where and when they were checked.",
                 "Written when a claim is verified; a claim without a source stays out.",
                 "Fields: claim, source, verified, by, time, from, supersedes."),
    VOCABULARY: ("ezexe's words a session misread, what they mean, and the exchange that proves it.",
                 "Written from corrections, retractions, missed details, repeats and follow-ups; the teacher model "
                 "fills in meanings, and ezexe edits it freely.",
                 "Fields: term, means, means-by, because, source, points-at, added, status; status is on or off."),
    MESSAGES: ("Every message one session received: when it came, how it arrived, and what was done about it.",
               "Opened by the prompt hook and completed by the close hook from the reply.",
               "Fields: fingerprint, time, arrival, state, addressed, recommended, match, freed-by, resembles; a "
               "migrated row adds from."),
}

# the word a retrieval line prints for a document, by the file or folder it comes from: plain words, never the
# file's name
KIND_NAMES = {"rules.md": "rule", "corrections.md": "correction", "retractions.md": "retracted", "facts.md": "fact",
              "memory": "memory", "messages": "earlier message", "src": "saved code"}

# words of the store's own design, which read as riddles to a session: p4.py's query drops a retrieval line that
# holds one, unless the line's document is plain. A document is plain when its entry has a `plain:` field, and every
# document of the repository and its dependencies is plain.
JARGON = re.compile(r"(?i)\b(frags?|rulings?|pour(ed|s)?|tombstones?|derivations?|the operator|register entry|"
                    r"read barrier|write barrier|dispatch row|hot tier|cold tier|pre-finalizers?|vlds|phi-index)\b(?!-)")

# words too ordinary to be a term of ezexe's own: never a dictionary term, never a rare term that makes a line
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
    """[Entry] from a corpus file's text: every column-0 `- key: value` line opens an entry, its two-space field
    lines follow, and a four-space line continues the field before it. A blank line is skipped. Any other line is
    skipped and ends the entry before it; the header's prose is such a line."""
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
    """A whole corpus file: its three header lines from HEADERS, then a blank line and the entries a blank line
    apart. A file HEADERS lacks gets three empty header lines."""
    key = MESSAGES if fname.startswith(MESSAGES + "/") else fname
    head = "\n".join(HEADERS.get(key, ("", "", "")))
    body = "\n\n".join(format_entry(p) for p in entries_pairs)
    return head + "\n\n" + body + ("\n" if body else "")


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def store_dir(p4):
    return p4conf.sub(p4, "store")


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
    """{file: [Entry]} for the four files of STORE_FILES and every session's file of messages, statuses applied."""
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

    Under the rule "new", equal owner-words free an entry unless both are dated and the entry is no older than the
    retraction; under "old" they free it whatever the dates. Under both, an entry's head and a retraction's `freed:` text free it when one contains the other and
    the shorter is at least MASK_MIN characters long."""
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


# --- the vocabulary dictionary ---------------------------------------------------------------------------

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


# --- short turns and resemblance -------------------------------------------------------------------------

def norm_token(text):
    """A text as the tokens messages are matched on: lower-cased, every punctuation mark but the apostrophe, the
    slash and the hyphen out, whitespace collapsed."""
    t = (text or "").lower().replace("…", " ").replace("’", "'")
    t = re.sub(r"[^\w\s'/-]", " ", t)
    return " ".join(t.split())


def unquote(v):
    v = (v or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v.strip()


def resembles(new, old):
    """True when a message's token set `new` resembles an earlier message's set `old`: the two are identical, or
    `new` has at least BARRIER_MIN_TOKENS tokens and their Jaccard similarity is at least BARRIER_JACCARD."""
    if not new or not old:
        return False
    if new == old:
        return True
    return len(new) >= BARRIER_MIN_TOKENS and len(new & old) / len(new | old) >= BARRIER_JACCARD


NOT_OWNER_ARRIVAL = re.compile(r"(?i)\s*(task notification|notification|agent message|hook injection)")


def owner_message(e, fp=None):
    """True for a row of ezexe's own words: its arrival is no notification, agent message or hook injection, and its
    fingerprint does not open with `<`, as a text Claude Code wraps in a tag does."""
    fp = unquote(e.fields.get("fingerprint", e.value)) if fp is None else fp
    return not NOT_OWNER_ARRIVAL.match(e.fields.get("arrival", "")) and not fp.lstrip().startswith("<")


def completed(e):
    return bool(e.fields.get("addressed", "").strip())


# --- what a document shows -------------------------------------------------------------------------------

def collapse(s):
    return re.sub(r"\s+", " ", unquote(s or "")).strip()


def kind_of(fname, e=None):
    if fname.startswith(MESSAGES + "/"):
        return KIND_NAMES["messages"]
    if fname == "corrections.md" and e is not None and ("omitted" in e.fields or "asked" in e.fields):
        return "missed detail"
    return KIND_NAMES.get(fname, fname)


def show_text(fname, e):
    """What a document shows in ordinary words, before the index and the retrieval line cut it: the `plain:` of the
    entry it comes from when that has one."""
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
    """The kind the ranker's `kind=` feature sees, finer than the printed kind for rulings and facts: a ruling with a
    `form:` is a form, and a fact is sourced or unsourced."""
    if fname == "rules.md":
        return "form" if e.fields.get("form", "").strip() else "rule"
    if fname == "facts.md":
        return "fact sourced" if e.fields.get("verified", "").strip() or e.fields.get("source", "").strip() \
            else "fact unsourced"
    return kind_of(fname, e)


def entry_text(e):
    """The words a document is indexed by: its head and every field but the bookkeeping ones."""
    return " ".join([e.value] + [v for k, v in e.pairs[1:] if k not in NOT_TEXT])


# --- memory and saved code, as documents -----------------------------------------------------------------

def stamp_of(path):
    import time as _t
    try:
        return _t.strftime("%Y-%m-%d %H:%M", _t.localtime(os.path.getmtime(path)))
    except OSError:
        return ""


def iso_stamp(value):
    """An ISO 8601 time as `YYYY-MM-DD HH:MM` in this machine's time, as stamp_of gives an mtime; '' when it does not
    parse."""
    import datetime as _d
    try:
        t = _d.datetime.fromisoformat(str(value).strip().strip("\"'").replace("Z", "+00:00"))
    except ValueError:
        return ""
    return (t.astimezone() if t.tzinfo else t).strftime("%Y-%m-%d %H:%M")


def memory_entries(p4):
    """The documents of the auto memory directory `temportal/memory/`, each an Entry: one per heading of every
    Markdown file but MEMORY.md, the index of links. The text before a file's first heading is one more document
    when it holds any, and a file without headings is that one document, headed by the frontmatter's description,
    else its name, else the file's. Each is dated by the frontmatter's `modified`, the ISO 8601 time Claude Code
    writes when Claude writes the file, else by the file's mtime, which a clone sets to the clone's time."""
    d = p4conf.sub(p4, "memory")
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
                m = re.match(r"^(description|name|modified):\s*(.*)$", lines[i])
                if m and m.group(1) == "modified":
                    when = iso_stamp(m.group(2)) or when
                elif m and (m.group(1) == "description" or not desc):
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
    """One document for each file of saved code under `temportal/src/`, an Entry holding its path and its first
    non-empty line that is no `#!` line, comment marks off. A file over 1 MiB, or one that does not read as UTF-8,
    is skipped."""
    d = p4conf.sub(p4, "src")
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
    return p4conf.sub(p4, "models", "index.json")


def sources_signature(p4):
    """(count, newest mtime_ns): the number of files under the corpus, `temportal/memory/` and `temportal/src/` plus
    repo.json and deps.json of `phi/models/`, and the newest mtime among those files and folders. It walks with
    os.scandir, one stat for each file or folder and no path joins, since every message's staleness check runs it."""
    count, newest = 0, 0
    for name in ("repo.json", "deps.json"):                        # the repository's and its dependencies' documents
        try:
            st_ = os.stat(p4conf.sub(p4, "models", name))
            count, newest = count + 1, max(newest, st_.st_mtime_ns)
        except OSError:
            pass
    stack = [p4conf.sub(p4, sub) for sub in ("store", "memory", "src")]
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
    """True when `phi/models/index.json` is missing or of another version, when a source is newer than it, or when
    the sources' count or newest mtime differs from what it was built on, as a deletion makes it differ."""
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
    """Where the file a document comes from is, relative to the store `.claude/p4`, by LAYOUT. The Entry's own `file`
    does not depend on LAYOUT: it is `memory/x.md`, `src/x.py` or a corpus file such as `rules.md`, so ids and labels
    stay the same wherever LAYOUT puts the folders."""
    top, _, rest = e.file.partition("/")
    if top in ("memory", "src") and rest:
        return p4conf.rel(top, rest)
    return p4conf.rel("store", e.file)


def make_doc(e, fname, kind):
    """The index's document for an Entry of the corpus, memory or saved code, with its term frequencies under `_tf`,
    which build_index turns into postings. Its `head`, the text the ranker's `head-bm25` feature reads in training
    and in the query alike, is for an entry of STORE_FILES its value collapsed and cut at HEAD_CHARS characters,
    each word with its repeats, and for any other entry the distinct words of its value's first 400 characters."""
    toks = ranker.tokens(entry_text(e))
    if fname in STORE_FILES:
        head = " ".join(ranker.tokens(collapse(e.value)[:HEAD_CHARS]))
    else:
        head = " ".join(dict.fromkeys(ranker.tokens(e.value[:400])))
    tf = {}
    for t in toks:
        tf[t] = tf.get(t, 0) + 1
    return {"id": e.id, "path": display_path(e), "line": e.line, "file": fname, "kind": kind,
            "time": e.time, "state": e.state, "show": show_text(fname, e)[:240],
            "plain": bool(e.fields.get("plain", "").strip()), "dl": len(toks), "_tf": tf,
            "toks": " ".join(tf), "head": head,
            **({"match": collapse(e.fields.get("match", ""))[:300]} if fname == "corrections.md" else {}),
            **({"supersedes": e.fields["supersedes"].strip()} if e.fields.get("supersedes", "").strip()
               else {}),
            **({"fkind": feature_kind(fname, e)} if feature_kind(fname, e) != kind else {})}


def held_docs(p4, files=None):
    """The corpus entries the index leaves out because they are FREED, SPENT or EXPIRED, as documents with their
    `_tf`. Retrieval never shows them, but train.with_held adds them to a pool task's candidates, since a pool label
    can name one of them, which the pool's reader saw with its state."""
    files = files if files is not None else load_store(p4)
    return [make_doc(e, fname, kind_of(fname, e)) for fname in STORE_FILES for e in files.get(fname, [])
            if e.state != "LIVE"]


def build_index(p4, write=True):
    """The index retrieval reads: one document for every LIVE entry of the four files of STORE_FILES, every completed
    row of ezexe's messages, every memory section and every head of saved code, and the documents of the repository
    and its dependencies, all tokenized, with BM25's postings; plus the short-turn table, each session's rows for the
    repeat line, and the vocabulary for expansion."""
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
                # a notification, an agent's message or a text Claude Code injects is not ezexe speaking: never a
                # line, never a short turn or a repeat
                excluded["not ezexe's"] = excluded.get("not ezexe's", 0) + 1
                continue
            tok = norm_token(fp)
            done = completed(e)
            addressed = collapse(e.fields.get("addressed", ""))
            rows.append([e.time, tok[:300], 1 if done else 0, addressed[:160]])
            if tok and len(tok.split()) <= SHORT_WORDS:
                short.setdefault(tok, []).append([e.time, s8, 1 if done else 0, addressed[:300], p4conf.rel("store", rel),
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
           # what a query reads of every document, kept apart so a query never decodes every row of load_index's Docs
           "dl": [d["dl"] for d in docs],
           "sup": [[d.get("time") or "", d["supersedes"]] for d in docs if d.get("supersedes")],
           "rule_at": rule_minutes(docs)}
    if write:
        # on disk the documents are rows and each term's postings a string, decoded only for a query's terms,
        # which halves the load time
        disk = dict(out)
        disk["doc_fields"] = list(DOC_FIELDS)
        disk["docs"] = [[d.get(k) for k in DOC_FIELDS] for d in docs]
        disk["post"] = {t: " ".join(map(str, v)) for t, v in post.items()}
        text = json.dumps(disk, separators=(",", ":"), ensure_ascii=False)
        ranker.write_atomic(index_path(p4), text)
        write_cache(p4, disk)          # so the next message's load_index finds a warm cache
    return out


DOC_FIELDS = ("id", "path", "line", "file", "kind", "time", "state", "show", "plain", "dl", "toks", "head", "match",
              "supersedes", "fkind")


def repo_docs(p4):
    """The documents of the repository from `phi/models/repo.json` and of its dependencies from deps.json beside it,
    which refresh_index in hook.py brings up to date at session start and at every turn end, as `p4.py index --repo`
    and `--deps` do by hand."""
    try:
        import repo
    except ImportError:
        return []
    try:
        out = repo.entries(p4)
    except (OSError, ValueError, KeyError):
        out = []
    try:                               # the dependencies' documents, less any id the repository's documents hold
        import deps
        have = {d["id"] for d in out}
        out += [d for d in deps.entries(p4) if d["id"] not in have]
    except (ImportError, OSError, ValueError, KeyError):
        pass
    return out


def cache_path(p4):
    # a name the seeded .gitignore's `phi/models/*.tmp` covers, so git ignores the cache in every seeded store
    return p4conf.sub(p4, "models", "index-cache.tmp")


def load_index(p4):
    """The index as build_index wrote it, its documents decoded into dicts as they are read. A hook is a new process
    for every message, so the decoded index is kept beside the JSON in `phi/models/index-cache.tmp`, in marshal,
    which loads in about a third of json.load's time. The cache is keyed on the JSON's mtime and size and
    INDEX_VERSION; one that does not match, or does not read, is rebuilt from the JSON and written again."""
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
    """Write `phi/models/index-cache.tmp`, the on-disk index in marshal, keyed on index.json's mtime and size and
    INDEX_VERSION. Its documents stay rows and its postings strings. Best effort."""
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
    """The index's documents, each decoded from its on-disk row into a dict the first time it is read: a query reads
    a few hundred of the index's thousands, so the rest are never built."""
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
    """{minute: [position in docs]} of the rulings, by the minute they were written, for p4.standing_first."""
    out = {}
    for i, d in enumerate(docs):
        if d["file"] == "rules.md" and d.get("time"):
            out.setdefault(d["time"][:16], []).append(i)
    return out


def postings(idx, term):
    """[document, tf, document, tf, ...] for one term, each document by its position in the index's documents, or
    None; an on-disk string is decoded on first use."""
    p = idx["post"].get(term)
    if isinstance(p, str):
        p = idx["post"][term] = [int(x) for x in p.split()]
    return p


def ensure_index(p4):
    """(index, rebuilt?): the index, rebuilt first when it is stale or does not load."""
    if index_stale(p4):
        return build_index(p4), True
    try:
        return load_index(p4), False
    except (OSError, ValueError):
        return build_index(p4), True


def find_p4(given=None, cwd=None):
    """The store `.claude/p4` of the directory given, else of CLAUDE_PROJECT_DIR, else of the working directory.
    Each is the store itself when it holds a `store` or `phi/store` folder, or when it is named p4 and a directory
    was given; otherwise its `.claude/p4` is the store when that folder exists. A directory given is returned as it
    is when neither holds, and None comes back when no store is found and none was given. A store found is put in
    LAYOUT's places by p4conf.migrate_layout first."""
    for base in (given, os.environ.get("CLAUDE_PROJECT_DIR"), cwd or os.getcwd()):
        if not base:
            continue
        base = os.path.abspath(base)
        if os.path.isdir(os.path.join(base, "store")) or os.path.isdir(p4conf.sub(base, "store"))                 or os.path.basename(base) == "p4" and given:
            p4conf.migrate_layout(base)
            return base
        cand = os.path.join(base, ".claude", "p4")
        if os.path.isdir(cand):
            p4conf.migrate_layout(cand)
            return cand
        if given:
            return base
    return None
