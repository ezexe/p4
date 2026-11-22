#!/usr/bin/env python3
"""labels.py: the labels the retrieval ranker trains on, and the tasks they label.

A label says whether a document bears on a task, 1 when it does and 0 when it does not, and its `entry` column holds
that document's id. It names the source that wrote it and carries a weight, which scales how much a round counts it;
as_label gives each source's weight. Three files under the store's phi/models/ hold the labels and their tasks:

  labels-raw.tsv  the labels drawn from the store's own records, before any teacher edit
                  columns: task, entry, label, source, weight, time, note
                  pool          a pick a reader made in a `recall-pool.md` or an audit file of the per-session
                                layout, as an earlier p4's migration imported it
                  store         `p4.py labels --from-history`: the documents that share rare terms with a completed
                                message's reply, for a message whose session has no pool
                  short         the same command: a short message's prior reading
  labels.tsv      the training set
                  columns: task, entry, label, source, weight, time, teacher, edited, note
                  store+edited  `p4.py teacher edit-labels`: 1 on a pick the teacher kept or added, 0 on one it
                                dropped; `teacher` names the model that answered and `edited` the date
                  usage         hook.py at turn end and when a subagent finishes: whether the turn used a served
                                line; the note says whether the lines were shown or only logged in shadow
                  repo          the same hooks and `p4.py labels --from-transcripts`: what a turn did with a file of
                                the repository
                  said          said.py: 1 on a line a session states it applied, 0 on one it set aside
  tasks.tsv       the tasks
                  columns: id, session, time, text, kind
                  kind: `short` for a message of at most SHORT_WORDS words, else `first` for a session's first
                  message from ezexe and `new` for any other; `agent` for a subagent's task

training_labels joins labels-raw.tsv and labels.tsv into what a round trains on.
"""

import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import ranker  # noqa: E402
import store as st  # noqa: E402

RAW = "labels-raw.tsv"
TRAIN = "labels.tsv"
TASKS = "tasks.tsv"
RAW_HEAD = ["task", "entry", "label", "source", "weight", "time", "note"]
TRAIN_HEAD = ["task", "entry", "label", "source", "weight", "time", "teacher", "edited", "note"]
TASK_HEAD = ["id", "session", "time", "text", "kind"]
USAGE_WEIGHT = 0.3            # low: no test measures how often the usage rule agrees with a teacher
HISTORY_WEIGHT = 0.5          # history labels agree with a teacher's at an F1 of 0.50 to 0.53
HISTORY_MAX = 5               # positives per history task
HISTORY_POOL = 120            # matches gathered per history task, from BM25's top 3 * HISTORY_POOL


# --- files -----------------------------------------------------------------------------------------------

def mpath(p4, name):
    return p4conf.sub(p4, "models", name)


def read_tsv(path):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except OSError:
        return []
    if not lines or not lines[0]:
        return []
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:] if l.strip()]


def clean(v):
    return re.sub(r"[\t\r\n]+", " ", str(v if v is not None else ""))


def write_tsv(path, head, rows):
    text = "\t".join(head) + "\n" + "".join("\t".join(clean(r.get(h, "")) for h in head) + "\n" for r in rows)
    ranker.write_atomic(path, text)


def append_tsv(path, head, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write("\t".join(head) + "\n")
        for r in rows:
            f.write("\t".join(clean(r.get(h, "")) for h in head) + "\n")


def read_tasks(p4):
    return {r["id"]: r for r in read_tsv(mpath(p4, TASKS)) if r.get("id")}


def add_tasks(p4, rows):
    """Append the tasks not already in tasks.tsv, no id twice; returns how many were appended."""
    have = read_tasks(p4)
    new = [r for r in rows if r["id"] not in have]
    seen = set()
    new = [r for r in new if not (r["id"] in seen or seen.add(r["id"]))]
    append_tsv(mpath(p4, TASKS), TASK_HEAD, new)
    return len(new)


def replace_source(p4, name, head, source, rows, tasks=None):
    """Rewrite one labels file with the rows of `source` replaced by `rows`: every such row, or with `tasks` given
    only those of the tasks it names."""
    path = mpath(p4, name)
    kept = [r for r in read_tsv(path) if not (r.get("source") == source and (tasks is None or r.get("task") in tasks))]
    write_tsv(path, head, kept + rows)


def count_labels(p4):
    return len(read_tsv(mpath(p4, RAW))) + len(read_tsv(mpath(p4, TRAIN)))


def as_label(r):
    """A labels row as a round reads it: label 1 or 0, and its weight. Each source's weight is 0.7 for `pool`,
    HISTORY_WEIGHT for `store`, USAGE_WEIGHT for `usage` and 1.0 for `short`, `store+edited` and `said`: each
    writer puts it on its rows, and a row whose weight is empty, zero or not a number reads at it. A `repo` row
    carries the weight transcript.WEIGHTS sets for what the turn did with the file, halved on the commit that last
    touched it, and reads at 1.0 without one, as a row of any source not named here does."""
    try:
        w = float(r.get("weight") or 0) or None
    except ValueError:
        w = None
    src = r.get("source", "")
    if w is None:
        w = {"pool": 0.7, "usage": USAGE_WEIGHT, "store": HISTORY_WEIGHT}.get(src, 1.0)
    return {"task": r.get("task", ""), "entry": r.get("entry", ""), "label": 1 if str(r.get("label")) == "1" else 0,
            "source": src, "weight": w, "time": r.get("time", ""), "note": r.get("note", "")}


BATCHES = "teacher-batches.json"
BATCH_RE = re.compile(r"(?:^|;\s*)batch:([^\s;]+)")


def batch_of(note):
    """The teacher batch a `store+edited` row came from, the `<id>` of its note's `batch:<id>`, or ''."""
    m = BATCH_RE.search(note or "")
    return m.group(1) if m else ""


def read_batches(p4):
    """`{batch id: {teacher, time, tasks, status: ok | held, why, ...}}` from phi/models/teacher-batches.json, or {}
    when the file is missing, unreadable or holds no object."""
    try:
        with open(mpath(p4, BATCHES), encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def held_batches(p4):
    """The ids of the teacher batches held for ezexe: teacher.py holds a batch whose second opinion agrees with it
    below teacher.AGREE_MIN, and a round of train.py holds every batch when the edited labels score below the raw
    ones."""
    return {k for k, v in read_batches(p4).items() if isinstance(v, dict) and v.get("status") == "held"}


def follow(entry, ids, renames):
    """A repo label's `entry` as the index holds it: itself when the index has that document; else the id of the same
    document under the path git renamed its file to; else the id of that file's own document, when only the symbol
    is gone. Unchanged when the index holds none of them, as for a deleted file or one never indexed on this
    machine."""
    if entry in ids or not entry.startswith("repo:"):
        return entry
    path, _, sym = entry[5:].partition("#")
    now = renames.get(path, path)
    for cand in ((f"repo:{now}#{sym}",) if sym else ()) + (f"repo:{now}",):
        if cand in ids:
            return cand
    return entry


def followed(p4, rows, idx):
    """`(rows, moved)`: the rows with the `entry` of each repo label moved by follow to the document the index holds,
    the renames read from repo.rename_map, and how many of them moved."""
    import repo
    ids = {d["id"] for d in idx["docs"]}
    ren = repo.rename_map(p4)
    out, moved = [], 0
    for r in rows:
        e = follow(r["entry"], ids, ren)
        moved += e != r["entry"]
        out.append(r if e == r["entry"] else {**r, "entry": e})
    return out, moved


def training_labels(p4, idx=None):
    """Every label a round trains on, each as as_label reads it: the labels.tsv rows, less the `store+edited` rows
    of a held teacher batch and, unless p4.json's `recall.said.mode` is `on`, the `said` rows; and the
    labels-raw.tsv rows of every task with no `store+edited` row left, so the tasks of a held batch keep their raw
    labels. The recency rule then applies. Given the index, a label on a file renamed after the label was written,
    or on a symbol gone from a file still there, moves by follow to the document the index holds: a round skips a
    label whose document the index lacks."""
    if idx is not None:
        got = recency(p4, _training_rows(p4))
        return followed(p4, got, idx)[0]
    return recency(p4, _training_rows(p4))


def _training_rows(p4):
    held = held_batches(p4)
    import said
    stated = said.mode(p4) == "on"          # p4.json's recall.said.mode, read by said.py
    train = [as_label(r) for r in read_tsv(mpath(p4, TRAIN))
             if not (held and r.get("source") == "store+edited" and batch_of(r.get("note", "")) in held)
             and (stated or r.get("source") != "said")]
    edited = {r["task"] for r in train if r["source"] == "store+edited"}
    raw = [as_label(r) for r in read_tsv(mpath(p4, RAW)) if r.get("task") not in edited]
    return raw + train


def superseding(p4):
    """`{older fact id: (newer fact id, newer time)}` from the `supersedes:` fields of facts.md."""
    out = {}
    for e in st.load_file(p4, "facts.md"):
        old = e.fields.get("supersedes", "").strip()
        if old:
            out[old] = (e.id, e.time)
    return out


def recency(p4, labels, report=None):
    """The recency rule: a positive label on a fact that a newer fact supersedes is dropped when its task is dated
    at or after the newer fact, or either is undated, and the newer fact takes its place as the positive, unless
    the task already has a label on it. A task's date is its time in tasks.tsv, else the label's own. A `report`
    list, when given, gets a line `<task>: <entry> dropped: superseded by <id>` for each label dropped."""
    sup = superseding(p4)
    if not sup:
        return labels
    tasks = read_tasks(p4)
    out, have = [], {(l["task"], l["entry"]) for l in labels}
    for l in labels:
        s = sup.get(l["entry"])
        when = tasks.get(l["task"], {}).get("time", "") or l.get("time", "")
        if s and l["label"] and (not s[1] or not when or when[:16] >= s[1][:16]):
            if report is not None:
                report.append(f"{l['task']}: {l['entry']} dropped: superseded by {s[0]}")
            if (l["task"], s[0]) not in have:
                out.append({**l, "entry": s[0], "note": f"newer than {l['entry']}"})
                have.add((l["task"], s[0]))
            continue
        out.append(l)
    return out


def per_source(p4):
    got = {}
    for r in read_tsv(mpath(p4, RAW)):
        got.setdefault(("labels-raw.tsv", r.get("source", "")), [0, 0])[0 if r.get("label") == "1" else 1] += 1
    for r in read_tsv(mpath(p4, TRAIN)):
        got.setdefault(("labels.tsv", r.get("source", "")), [0, 0])[0 if r.get("label") == "1" else 1] += 1
    return got


# --- rare terms, shared by history and usage labels ------------------------------------------------------

def rare_of(idx, toks):
    n = idx["n"]
    out = set()
    for t in toks:
        if t in st.COMMON or t.isdigit() or len(t) < 3:
            continue
        p = st.postings(idx, t)
        if p and ranker.is_rare(len(p) // 2, n):
            out.add(t)
    return out


PATH_RE = re.compile(r"(?<![\w.-])((?:[\w.-]+/)+[\w.-]+\.\w{1,8}|[\w-]{3,}\.(?:py|md|json|sh|ts|js|cc|hh|cpp|h|hpp|"
                     r"cmake|txt|toml|yml|yaml|swift|rs|go|mm|m))(?![\w-])")


def paths_named(text):
    return set(PATH_RE.findall(text or ""))


def used(doc, rare_doc, hay_toks, hay_text, prompt_text):
    """The usage rule: a document was used when `hay_toks`, the tokens of `hay_text`, hold two of its rare terms
    `rare_doc`, or `hay_text` holds a path the document names that `prompt_text` does not. For a usage label
    `hay_text` is the turn's reply and what the turn wrote. A document of the repository counts its own path among
    the paths it names."""
    if len(rare_doc & hay_toks) >= 2:
        return True
    for p in paths_named(doc.get("show", "")) | ({doc["path"]} if doc.get("file") == "repo" else set()):
        if p and p in hay_text and p not in (prompt_text or ""):
            return True
    return False


# --- the history labels of `p4.py labels --from-history` -------------------------------------------------

MARKERS = ("no", "not", "i meant", "i mean", "should have", "incorrect", "wrong", "again")   # a correction opens so


def fp(e):
    """A message row's text: its fingerprint, unquoted, or its value."""
    return st.unquote(e.fields.get("fingerprint", e.value))


def turn_rows(rows):
    """ezexe's own messages: notifications, agent messages and hook injections out."""
    return [r for r in rows if not re.match(r"(?i)\s*(task notification|agent message|hook injection)",
                                            r.fields.get("arrival", "")) and not fp(r).lstrip().startswith("<")]


def minutes(a, b):
    """The minutes from the time `a` to the time `b`, each `YYYY-MM-DD HH:MM`, or None where either is no time."""
    try:
        x = datetime.datetime.strptime(a[:16], "%Y-%m-%d %H:%M")
        y = datetime.datetime.strptime(b[:16], "%Y-%m-%d %H:%M")
        return (y - x).total_seconds() / 60
    except (ValueError, TypeError):
        return None


def message_rows(files):
    """`[(s8, rows)]` sorted by session, each session's rows cut to ezexe's own messages by turn_rows, which
    drops task notifications, agent messages, hook injections and any message that opens with `<`."""
    out = []
    for rel in sorted(k for k in files if k.startswith(st.MESSAGES + "/")):
        out.append((rel[len(st.MESSAGES) + 1:-3], turn_rows(files[rel])))
    return out


def task_of_row(s8, e, first):
    fp = st.unquote(e.fields.get("fingerprint", e.value))
    kind = "short" if len(st.norm_token(fp).split()) <= st.SHORT_WORDS else ("first" if first else "new")
    return {"id": e.id, "session": s8, "time": e.time[:16], "text": st.collapse(fp)[:2000], "kind": kind}


def from_history(p4, idx=None, files=None):
    """`p4.py labels --from-history`: writes the history labels of the completed message rows, the `store` and
    `short` sources of labels-raw.tsv, rewritten whole, and adds the tasks they label to tasks.tsv. Returns the
    counts.

    A row of at most SHORT_WORDS words takes a `short` label on a prior completed row of the same words when the
    two replies resemble each other. Any other row, in a session with no pool or audit task, takes a `store` label
    on up to HISTORY_MAX documents from BM25's top candidates for its reply, the best by shared rare terms. Such a
    document is not dated after the row and is not built from a message row, and either two of its rare terms are
    in the reply, one of them not in the message, or it is a document of the repository whose path the reply names
    and the message does not.
    A row's reply is its `addressed:` paragraph and the `meant:` of the corrections of the same hour."""
    import p4 as cli
    if idx is None:
        idx, _ = st.ensure_index(p4)
    files = files or st.load_store(p4)
    tasks = read_tasks(p4)
    pooled = {t["session"][:8] for t in tasks.values() if t["id"].startswith(("pool:", "audit:"))}
    docs = idx["docs"]
    new_tasks, hist, short = [], [], []
    by_token = {}
    corrections = {}
    for e in files.get("corrections.md", []):
        corrections.setdefault(e.time[:13], []).append(st.collapse(e.fields.get("meant", "")))
    stats = {"rows": 0, "history_tasks": 0, "history_labels": 0, "short_tasks": 0, "short_labels": 0}
    for s8, rows in message_rows(files):
        first = True
        for e in rows:
            if not st.completed(e):
                first = False
                continue
            stats["rows"] += 1
            t = task_of_row(s8, e, first)
            first = False
            addressed = st.collapse(e.fields.get("addressed", ""))
            tok = st.norm_token(t["text"])
            if t["kind"] == "short":
                prior = by_token.get(tok, [])
                if prior:
                    a = set(st.norm_token(prior[-1][1]).split())
                    b = set(st.norm_token(addressed).split())
                    if st.resembles(b, a):
                        short.append({"task": t["id"], "entry": prior[-1][0], "label": "1", "source": "short",
                                      "weight": "1.0", "time": t["time"], "note": "its earlier reading"})
                        new_tasks.append(t)
                        stats["short_tasks"] += 1
                by_token.setdefault(tok, []).append((e.id, addressed))
                continue
            if s8 in pooled:
                continue
            hay = addressed + " " + " ".join(corrections.get(e.time[:13], []))
            hay_toks = set(ranker.tokens(hay))
            prompt_toks = set(ranker.tokens(t["text"]))
            terms = list(dict.fromkeys(ranker.tokens(hay)))
            if not terms:
                continue
            scores = cli.bm25_scores(idx, terms, {})
            cand = sorted(scores, key=lambda i: (-scores[i], i))
            got = []
            for i in cand[:HISTORY_POOL * 3]:
                d = docs[i]
                if d["file"] == "messages" or (d.get("time") and d["time"][:16] > t["time"]):
                    continue
                rd = rare_of(idx, d["toks"].split())
                shared = rd & hay_toks
                if len(shared) >= 2 and len(shared - prompt_toks) >= 1 or used(d, set(), set(), hay, t["text"]) \
                        and d["file"] == "repo":
                    got.append((len(shared), -i, d["id"]))
                if len(got) >= HISTORY_POOL:
                    break
            got.sort(reverse=True)
            if not got:
                continue
            new_tasks.append(t)
            stats["history_tasks"] += 1
            for _, _, eid in got[:HISTORY_MAX]:
                hist.append({"task": t["id"], "entry": eid, "label": "1", "source": "store", "weight":
                             str(HISTORY_WEIGHT), "time": t["time"], "note": "shares the reply's rare terms"})
    stats["history_labels"], stats["short_labels"] = len(hist), len(short)
    path = mpath(p4, RAW)
    kept = [r for r in read_tsv(path) if r.get("source") not in ("store", "short")]
    write_tsv(path, RAW_HEAD, kept + hist + short)
    add_tasks(p4, new_tasks)
    return stats


# --- usage labels, written by the Stop and SubagentStop hooks --------------------------------------------

def served_path(p4, key):
    return p4conf.sub(p4, "models", "served", re.sub(r"[^\w.-]", "_", key) + ".json")


def write_served(p4, key, record):
    ranker.write_atomic(served_path(p4, key), json.dumps(record, ensure_ascii=False))


def read_served(p4, key):
    try:
        with open(served_path(p4, key), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def tool_inputs(turn):
    """What the turn wrote: the `file_path`, `new_string`, `content` and `edits` of each edit tool's input, and the
    `command` of each Bash and PowerShell call."""
    out = []
    for c in (turn or {}).get("calls", []):
        inp = c.get("input") if isinstance(c.get("input"), dict) else {}
        if c["name"] in ("Edit", "Write", "NotebookEdit"):
            out.append(" ".join(str(inp.get(k, "")) for k in ("file_path", "new_string", "content", "edits")))
        elif c["name"] in ("Bash", "PowerShell"):
            out.append(str(inp.get("command", "")))
    return "\n".join(out)


def served_mode(served):
    """"shown" when the served lines reached the model, "shadow" when they were only logged, by the record's
    `shadow` flag or else its count of lines `shown`, and "" when it has no flag and no lines shown. hook.py's
    h_recall writes both fields and h_agent the flag alone."""
    if served.get("shadow") is True:
        return "shadow"
    if served.get("shadow") is False or served.get("shown"):
        return "shown"
    return ""


def usage_labels(p4, idx, served, reply, turn=None, task_id="", now=""):
    """[label row] for each served document the index holds: 1 when the turn used it by the usage rule and 0 when it
    did not, source `usage`, weight USAGE_WEIGHT. Rare terms the prompt holds do not count toward a use. The note
    keeps whether the lines were shown or only logged in shadow, as `used; shown` or `unused; shadow`: the hook
    deletes the served record after it writes the labels, and a label on a line the model never saw measures
    retrieval's ranking, not the model's uptake."""
    by = {d["id"]: d for d in idx["docs"]}
    hay = (reply or "") + "\n" + tool_inputs(turn)
    hay_toks = set(ranker.tokens(hay))
    prompt = served.get("text", "")
    prompt_toks = set(ranker.tokens(prompt))
    mode = served_mode(served)
    out = []
    for eid in served.get("ids", []):
        d = by.get(eid)
        if not d:
            continue
        rd = rare_of(idx, d["toks"].split()) - prompt_toks
        u = used(d, rd, hay_toks, hay, prompt)
        out.append({"task": task_id or served.get("task", ""), "entry": eid, "label": "1" if u else "0",
                    "source": "usage", "weight": str(USAGE_WEIGHT), "time": now, "teacher": "", "edited": "",
                    "note": ("used" if u else "unused") + (f"; {mode}" if mode else "")})
    return out


def working_texts(p4, limit=200):
    """The dictionary check's working set: the texts of the tasks whose served lines were used, a `usage` label 1,
    and whose next message was no follow-up, at most `limit` of them, the last in labels.tsv."""
    tasks = read_tasks(p4)
    good = []
    for r in read_tsv(mpath(p4, TRAIN)):
        if r.get("source") == "usage" and r.get("label") == "1" and r.get("task") in tasks:
            t = tasks[r["task"]]
            if t["text"] not in good and not followed_up(p4, t):
                good.append(t["text"])
    return good[-limit:]


def followed_up(p4, task):
    s8 = (task.get("session") or "")[:8]
    rows = turn_rows(st.load_file(p4, f"{st.MESSAGES}/{s8}.md")) if s8 else []
    for i, e in enumerate(rows[:-1]):
        if e.id == task["id"]:
            return is_follow_up(e, rows[i + 1])
    return False


def is_follow_up(prev, cur):
    """The follow-up detector: `cur` starts with one of the correction markers MARKERS, or it resembles
    `prev` by st.resembles and was sent no more than 10 minutes after it. No test measures its precision."""
    text = st.norm_token(fp(cur))
    if any(text == m or text.startswith(m + " ") for m in MARKERS):
        return True
    close = minutes(prev.time, cur.time)
    return close is not None and close <= 10 and st.resembles(set(text.split()),
                                                               set(st.norm_token(fp(prev)).split()))


# --- repo labels: what a turn did with the repository's files --------------------------------------------

def repo_index(idx):
    """The index's documents of the repository as five lookups: the known paths, `{path: [symbol]}`,
    `{path: document id}`, `{path: [(symbol, document id)]}` and `{path: id of the document of the newest commit
    that names it}`."""
    known, syms, path_id, sym_ids, commit_of = set(), {}, {}, {}, {}
    for d in idx["docs"]:
        if d["file"] == "repo":
            p = d["path"]
            known.add(p)
            if d["id"] == f"repo:{p}":
                path_id[p] = d["id"]
            else:
                s = d["show"].split(" — ", 1)[1] if " — " in d["show"] else ""
                syms.setdefault(p, []).append(s)
                sym_ids.setdefault(p, []).append((s, d["id"]))
    for d in idx["docs"]:
        if d["file"] == "commit":
            for p in re.findall(r"[\w./+-]+", d["show"].rsplit("(", 1)[-1]):
                if p in known and (p not in commit_of or d["time"] > commit_of[p][1]):
                    commit_of[p] = (d["id"], d["time"])
    return known, syms, path_id, sym_ids, {p: v[0] for p, v in commit_of.items()}


def turn_repo_labels(turn, project, ri, task_id, reply="", now="", p4=""):
    """`(rows, events)` for one turn: a label row on the document of each repository file the turn touched, by
    transcript.file_events, with the label and weight transcript.WEIGHTS sets for its event. A positive label also
    lands on each of the file's symbols whose name, its last `::` part, is four characters or more and appears as
    a word in what the turn wrote or in its reply, and at half the weight on the newest commit that touched the
    file. Given `p4`, transcript.EXTERNAL is set from deps.externals, so a file of a dependency outside the project
    counts too."""
    import transcript as tr
    known, syms, path_id, sym_ids, commit_of = ri
    if p4:
        import deps
        tr.EXTERNAL = deps.externals(p4)
    ev = tr.file_events(turn, project, known, syms, reply)
    out = []
    edit_text = tool_inputs(turn)
    for p, e in sorted(ev.items()):
        lab, w = tr.WEIGHTS[e["label"]]
        if p not in path_id:
            continue
        row = {"task": task_id, "entry": path_id[p], "label": str(lab), "source": "repo", "weight": str(w),
               "time": now or turn.get("time", ""), "teacher": "", "edited": "", "note": e["label"]}
        out.append(row)
        if lab:
            for s, sid in sym_ids.get(p, []):
                last = s.split("::")[-1]
                if len(last) >= 4 and re.search(r"(?<!\w)" + re.escape(last) + r"(?!\w)", edit_text + " " + reply):
                    out.append({**row, "entry": sid, "note": e["label"] + " (symbol)"})
            if p in commit_of:
                out.append({**row, "entry": commit_of[p], "weight": str(round(w * 0.5, 2)),
                            "note": e["label"] + " (its last commit)"})
    return out, ev


def transcript_files(slug_dir, s8):
    try:
        return sorted(os.path.join(slug_dir, n) for n in os.listdir(slug_dir)
                      if n.startswith(s8) and n.endswith(".jsonl"))
    except OSError:
        return []


def match_row(rows, turn):
    """The message row a transcript turn is: the first row whose fingerprint resembles the turn's prompt by
    st.resembles, or whose three or more words all appear in it, each side read to 300 characters; None when no
    row does."""
    tt = set(st.norm_token(turn["prompt"][:300]).split())
    for e in rows:
        fp = set(st.norm_token(st.unquote(e.fields.get("fingerprint", e.value))[:300]).split())
        if fp and st.resembles(tt, fp) or (fp and tt and fp <= tt and len(fp) >= 3):
            return e
    return None


_DEP_PATHS = {}


def is_dep_entry(p4, entry):
    """True when a label's `entry` names a dependency's document: a `repo:` id whose path sits in a package that
    deps.py's state holds. A store's package paths are read on its first call and kept in _DEP_PATHS."""
    import deps
    if p4 not in _DEP_PATHS:
        s = deps.load_state(p4)
        _DEP_PATHS[p4] = tuple(v["path"] for rs in s.get("roots", {}).values() for v in rs["packages"].values())
    p = entry[5:].split("#", 1)[0] if entry.startswith("repo:") else ""
    return bool(p) and any(p == d or p.startswith(d + "/") for d in _DEP_PATHS[p4])


def from_transcripts(p4, project, slug_dirs, idx=None, write=True, all_sessions=False):
    """`p4.py labels --from-transcripts`: the repo labels of every turn of the transcripts in `slug_dirs`, the
    ~/.claude/projects/<slug>/ directories: those of the sessions that have a message file in the corpus, or all
    of them with `all_sessions`. A turn's task is the message row match_row finds, else a task of its own,
    `turn:<s8>:<time>`. With `write`, it rewrites every `repo` row of labels.tsv, those of the hooks among them,
    and adds the tasks. The dependency files the turns opened that the index lacks go to deps.note_opened, so the
    next build of the dependency index reads them and a second pass can label them. Returns the counts, with
    `dep_opened` the number of those files that were not noted before."""
    import deps
    import transcript as tr
    if idx is None:
        idx, _ = st.ensure_index(p4)
    ri = repo_index(idx)
    files = st.load_store(p4)
    sessions = {rel[len(st.MESSAGES) + 1:-3]: ents for rel, ents in files.items() if rel.startswith(st.MESSAGES + "/")}
    stats = {"transcripts": 0, "turns": 0, "tasks": 0, "labels": {}, "matched_rows": 0}
    rows_out, tasks_out, opened = [], [], []
    names = set()
    for d in slug_dirs:
        try:
            names.update((d, n[:8]) for n in os.listdir(d) if n.endswith(".jsonl"))
        except OSError:
            pass
    for d, s8 in sorted(names):
        if s8 not in sessions and not all_sessions:
            continue
        for path in transcript_files(d, s8):
            stats["transcripts"] += 1
            for k, turn in enumerate(tr.turns(path)):
                stats["turns"] += 1
                e = match_row(sessions.get(s8, []), turn)
                if e is not None:
                    stats["matched_rows"] += 1
                    tid = e.id
                else:
                    tid = f"turn:{s8}:{turn['time']}"
                labs, _ = turn_repo_labels(turn, project, ri, tid, tr.reply_of(turn), turn["time"], p4=p4)
                opened += [p for p in deps.opened_in_turn(turn, project) if p not in ri[0]]
                if not labs:
                    continue
                tasks_out.append({"id": tid, "session": s8, "time": turn["time"][:16],
                                  "text": st.collapse(turn["prompt"])[:2000],
                                  "kind": "short" if len(st.norm_token(turn["prompt"]).split()) <= st.SHORT_WORDS
                                  else "new"})
                for r in labs:
                    stats["labels"][r["note"].split(" ")[0]] = stats["labels"].get(r["note"].split(" ")[0], 0) + 1
                rows_out += labs
    stats["tasks"] = len({t["id"] for t in tasks_out})
    stats["rows"] = len(rows_out)
    stats["dep_rows"] = sum(1 for r in rows_out if is_dep_entry(p4, r["entry"]))
    stats["dep_opened"] = deps.note_opened(p4, list(dict.fromkeys(opened)))
    if write:
        replace_source(p4, TRAIN, TRAIN_HEAD, "repo", rows_out)
        add_tasks(p4, tasks_out)
    return stats


# --- the re-exploration measure: what a turn spent before it opened the file it needed -------------------

def reexploration(p4, project, slug_dirs, idx=None, k=5):
    """The re-exploration measure over every transcript in `slug_dirs`: for each turn that opened a file which it,
    or a later turn of its transcript, edited, invoked or cited, the tool calls and input tokens spent before that
    first open, and whether the top k that p4.rank gives the prompt named the file. When it did, the turn could
    have read the file straight away: the counterfactual cost is one call and the input tokens before the turn's
    first call. Returns the means per turn, `hit_rate` for the share of turns whose top k named the file, and the
    rows."""
    import p4 as cli
    import transcript as tr
    if idx is None:
        idx, _ = st.ensure_index(p4)
    ri = repo_index(idx)
    known, syms = ri[0], ri[1]
    by = {d["id"]: d for d in idx["docs"]}
    rows = []
    for d in slug_dirs:
        try:
            names = sorted(n for n in os.listdir(d) if n.endswith(".jsonl"))
        except OSError:
            continue
        for n in names:
            ts = tr.turns(os.path.join(d, n))
            # relevant: edited, invoked or cited by this turn or a later one of the transcript
            evs = [tr.file_events(t, project, known, syms, tr.reply_of(t)) for t in ts]
            for i, t in enumerate(ts):
                later = set()
                for ev in evs[i:]:
                    later |= {p for p, e in ev.items() if e["label"] in ("edited", "invoked", "cited")}
                got = tr.exploration(t, evs[i], later)
                if got is None:
                    continue
                calls, tokens, path = got
                top = cli.rank(p4, t["prompt"][:4000], idx=idx, k=k, now=t["time"][:16])
                paths = {by[x]["path"] for x in top if x in by and by[x]["file"] == "repo"}
                hit = path in paths
                first_tokens = t["calls"][0]["tokens_before"] if t["calls"] else 0
                rows.append({"session": n[:8], "time": t["time"], "calls": calls, "tokens": tokens, "path": path,
                             "hit": hit, "cf_calls": 1 if hit else calls,
                             "cf_tokens": first_tokens if hit else tokens})
    n = len(rows)
    if not n:
        return {"turns": 0}
    return {"turns": n, "calls": sum(r["calls"] for r in rows) / n, "cf_calls": sum(r["cf_calls"] for r in rows) / n,
            "tokens": sum(r["tokens"] for r in rows) / n, "cf_tokens": sum(r["cf_tokens"] for r in rows) / n,
            "hit_rate": sum(r["hit"] for r in rows) / n, "rows": rows}
