#!/usr/bin/env python3
"""labels.py: the label set (fresh-marketplace.md 5.1, 5.1a, 5.2) and the dictionary's signals (5.3).

Two files under models/:
  labels-raw.tsv  the store's own labels, before any teacher edit: `pool` (old pools, imported), `store` (the history
                  labels of a task without a pool), `short` (a short turn's earlier reading), `miss` (an entry a
                  later correction shows would have prevented a misreading)
                  columns: task, entry, label, source, weight, time, note
  labels.tsv      the training set: the teacher's `store+edited` rows (step 9, paid, not built here) and the labels
                  the hooks write every turn: `usage` (served lines used or not; the note says whether they were
                  shown to the model or logged in shadow: `used; shown`, `unused; shadow`) and `repo` (the files
                  a turn edited, cited, dropped or never opened)
                  columns: task, entry, label, source, weight, time, teacher, edited, note
`training_labels` joins them: every labels.tsv row, and the labels-raw.tsv rows of every task the teacher has not
edited; then the recency rule (1a, 5.2) drops a label resting on a fact a newer fact supersedes and adds the newer
one in its place.

tasks.tsv holds the tasks: id, session, time, text, kind (new | short | agent as the hooks write them; `first`
only in tasks migrated from an old store's pools).
"""

import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ranker  # noqa: E402
import store as st  # noqa: E402

RAW = "labels-raw.tsv"
TRAIN = "labels.tsv"
TASKS = "tasks.tsv"
RAW_HEAD = ["task", "entry", "label", "source", "weight", "time", "note"]
TRAIN_HEAD = ["task", "entry", "label", "source", "weight", "time", "teacher", "edited", "note"]
TASK_HEAD = ["id", "session", "time", "text", "kind"]
USAGE_WEIGHT = 0.3            # until 8.1's agreement test raises it
HISTORY_WEIGHT = 0.5
HISTORY_MAX = 5               # positives per history task
HISTORY_POOL = 120            # BM25 candidates a history task's reply is checked against
NOTIFY_RE = re.compile(r"^\s*<(task-notification|system-reminder|local-command|command-name|bash-|user-prompt)",
                       re.I)


# --- files -----------------------------------------------------------------------------------------------

def mpath(p4, name):
    return os.path.join(p4, "models", name)


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
    """Append the tasks not already in tasks.tsv."""
    have = read_tasks(p4)
    new = [r for r in rows if r["id"] not in have]
    seen = set()
    new = [r for r in new if not (r["id"] in seen or seen.add(r["id"]))]
    append_tsv(mpath(p4, TASKS), TASK_HEAD, new)
    return len(new)


def replace_source(p4, name, head, source, rows, tasks=None):
    """Rewrite one labels file with every row of `source` (limited to `tasks` when given) replaced by `rows`."""
    path = mpath(p4, name)
    kept = [r for r in read_tsv(path) if not (r.get("source") == source and (tasks is None or r.get("task") in tasks))]
    write_tsv(path, head, kept + rows)


def count_labels(p4):
    return len(read_tsv(mpath(p4, RAW))) + len(read_tsv(mpath(p4, TRAIN)))


def as_label(r):
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
    """The teacher batch a `store+edited` row came from (its note's `batch:<id>`), or ''."""
    m = BATCH_RE.search(note or "")
    return m.group(1) if m else ""


def read_batches(p4):
    """{batch id: {teacher, time, tasks, status: ok | held, why, ...}} from models/teacher-batches.json."""
    try:
        with open(mpath(p4, BATCHES), encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def held_batches(p4):
    """The teacher batches held for the owner (5.6: a second opinion below 0.65, or edited below raw): their rows
    are not trained on, and the raw labels of their tasks stand in."""
    return {k for k, v in read_batches(p4).items() if isinstance(v, dict) and v.get("status") == "held"}


def training_labels(p4, idx=None):
    """Every label a round trains on (module docstring), the recency rule applied. A held teacher batch's rows are
    left out (its tasks keep their raw labels)."""
    held = held_batches(p4)
    train = [as_label(r) for r in read_tsv(mpath(p4, TRAIN))
             if not (held and r.get("source") == "store+edited" and batch_of(r.get("note", "")) in held)]
    edited = {r["task"] for r in train if r["source"] == "store+edited"}
    raw = [as_label(r) for r in read_tsv(mpath(p4, RAW)) if r.get("task") not in edited]
    return recency(p4, raw + train)


def superseding(p4):
    """{older fact id: (newer fact id, newer time)} from facts.md's `supersedes:` fields."""
    out = {}
    for e in st.load_file(p4, "facts.md"):
        old = e.fields.get("supersedes", "").strip()
        if old:
            out[old] = (e.id, e.time)
    return out


def recency(p4, labels, report=None):
    """5.2's recency rule: a label on a superseded fact, for a task dated after the newer fact, is dropped (listed
    in `report` as `dropped: superseded by <id>`), and the newer fact takes its place as the positive."""
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


# --- old pools (5.1's last row) --------------------------------------------------------------------------

def from_pools(p4, old):
    """Import the labelled pools and audits of an old-layout tree `old` into this store's labels-raw.tsv (source
    `pool`) and tasks.tsv, each pick resolved to an entry id by migrate.py's rule. Returns the stats."""
    import migrate
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    plan = migrate.build_plan(os.path.abspath(old), now)
    _texts, files = migrate.new_files(plan)
    tasks, labels, stats = migrate.import_pools(plan, files)
    rows = [dict(zip(RAW_HEAD, r)) for r in labels]
    replace_source(p4, RAW, RAW_HEAD, "pool", rows)
    add_tasks(p4, [dict(zip(TASK_HEAD, t)) for t in tasks])
    return {"tasks": len(tasks), "labels": len(rows), "unresolved": len(stats["unresolved"])}


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


def used(doc, rare_doc, hay_toks, hay_text, prompt_text, prompt_toks):
    """5.1's usage rule: the reply or the turn's Edit/Write/Bash inputs contain two of the entry's rare terms, or a
    path it names that the prompt did not."""
    if len(rare_doc & hay_toks) >= 2:
        return True
    for p in paths_named(doc.get("show", "")) | ({doc["path"]} if doc.get("file") == "repo" else set()):
        if p and p in hay_text and p not in (prompt_text or ""):
            return True
    return False


# --- the history labels: tasks without a pool (5.2 step 1) -----------------------------------------------

def message_rows(files):
    """[(s8, rows)] in session order; rows the owner's own (notifications and harness injections out)."""
    import migrate
    out = []
    for rel in sorted(k for k in files if k.startswith(st.MESSAGES + "/")):
        out.append((rel[len(st.MESSAGES) + 1:-3], migrate.turn_rows(files[rel])))
    return out


def task_of_row(s8, e, first):
    fp = st.unquote(e.fields.get("fingerprint", e.value))
    kind = "short" if len(st.norm_token(fp).split()) <= st.SHORT_WORDS else ("first" if first else "new")
    return {"id": e.id, "session": s8, "time": e.time[:16], "text": st.collapse(fp)[:2000], "kind": kind}


def from_history(p4, idx=None, files=None):
    """The `store` labels of every completed row whose session has no pool task, and the `short` labels of every
    completed short row (5.1, 5.4). Rewrites those two sources in labels-raw.tsv; adds the tasks."""
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
                if len(shared) >= 2 and len(shared - prompt_toks) >= 1 or used(d, set(), set(), hay, t["text"],
                                                                                 prompt_toks) and d["file"] == "repo":
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


# --- usage labels (5.1), the close hooks -----------------------------------------------------------------

def served_path(p4, key):
    return os.path.join(p4, "models", "served", re.sub(r"[^\w.-]", "_", key) + ".json")


def write_served(p4, key, record):
    ranker.write_atomic(served_path(p4, key), json.dumps(record, ensure_ascii=False))


def read_served(p4, key):
    try:
        with open(served_path(p4, key), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def tool_inputs(turn):
    """The text of the turn's Edit/Write/Bash inputs."""
    out = []
    for c in (turn or {}).get("calls", []):
        inp = c.get("input") if isinstance(c.get("input"), dict) else {}
        if c["name"] in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            out.append(" ".join(str(inp.get(k, "")) for k in ("file_path", "new_string", "content", "edits")))
        elif c["name"] == "Bash":
            out.append(str(inp.get("command", "")))
    return "\n".join(out)


def served_mode(served):
    """"shown" when the served lines reached the model, "shadow" when they were only logged (the record's `shown`
    count or `shadow` flag, hook.py h_recall / h_agent), "" for a record from before the fields."""
    if served.get("shadow") is True:
        return "shadow"
    if served.get("shadow") is False or served.get("shown"):
        return "shown"
    return ""


def usage_labels(p4, idx, served, reply, turn=None, task_id="", now=""):
    """[label row] for each entry served: used (1) or unused (0), source `usage`, weight USAGE_WEIGHT. The note
    keeps whether the lines were shown or shadow (`used; shown`, `unused; shadow`): the served record is deleted
    at Stop, and a label on a line the model never saw measures recall's ranking, not the model's uptake."""
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
        u = used(d, rd, hay_toks, hay, prompt, prompt_toks)
        out.append({"task": task_id or served.get("task", ""), "entry": eid, "label": "1" if u else "0",
                    "source": "usage", "weight": str(USAGE_WEIGHT), "time": now, "teacher": "", "edited": "",
                    "note": ("used" if u else "unused") + (f"; {mode}" if mode else "")})
    return out


def working_texts(p4, limit=200):
    """Prompts whose served lines were used (a `usage` label 1) and whose next prompt was no follow-up: the
    dictionary check's working set."""
    tasks = read_tasks(p4)
    good = []
    for r in read_tsv(mpath(p4, TRAIN)):
        if r.get("source") == "usage" and r.get("label") == "1" and r.get("task") in tasks:
            t = tasks[r["task"]]
            if t["text"] not in good and not followed_up(p4, t):
                good.append(t["text"])
    return good[-limit:]


def followed_up(p4, task):
    import migrate
    s8 = (task.get("session") or "")[:8]
    rows = migrate.turn_rows(st.load_file(p4, f"{st.MESSAGES}/{s8}.md")) if s8 else []
    for i, e in enumerate(rows[:-1]):
        if e.id == task["id"]:
            return is_follow_up(e, rows[i + 1])
    return False


def is_follow_up(prev, cur):
    """5.3's follow-up detector: the next message starts with a correction marker, or resembles the prior one at
    Jaccard >= 0.5 within 10 minutes. **Untested** as a detector (its precision is judged by hand, 8.1)."""
    import migrate
    text = st.norm_token(migrate.fp(cur))
    if any(text == m or text.startswith(m + " ") for m in migrate.MARKERS):
        return True
    close = migrate.minutes(prev.time, cur.time)
    return close is not None and close <= 10 and st.resembles(set(text.split()),
                                                               set(st.norm_token(migrate.fp(prev)).split()))


# --- repo labels from transcripts (5.1a) -----------------------------------------------------------------

def repo_index(idx):
    """(known paths, {path: [symbols]}, {path: entry id}, {path: [symbol entry ids]}, {path: newest commit id})."""
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


def turn_repo_labels(turn, project, ri, task_id, reply="", now=""):
    """[label row] for one turn: each file the turn touched, by 5.1a's table, on its path entry; an edited or cited
    file's label also lands on the symbols its edits name and on the newest commit that touched it."""
    import transcript as tr
    known, syms, path_id, sym_ids, commit_of = ri
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
    """The message row a transcript turn is: the same fingerprint (resembling), timed within a few minutes."""
    tt = set(st.norm_token(turn["prompt"][:300]).split())
    for e in rows:
        fp = set(st.norm_token(st.unquote(e.fields.get("fingerprint", e.value))[:300]).split())
        if fp and st.resembles(tt, fp) or (fp and tt and fp <= tt and len(fp) >= 3):
            return e
    return None


def from_transcripts(p4, project, slug_dirs, idx=None, write=True, all_sessions=False):
    """`labels --from-transcripts`: the repo labels of every turn of every transcript a message row names (by its
    session's first 8 characters), under the given ~/.claude/projects/<slug>/ directories. Rewrites the `repo`
    source in labels.tsv; adds the tasks (a turn no row matches becomes a task of its own)."""
    import transcript as tr
    if idx is None:
        idx, _ = st.ensure_index(p4)
    ri = repo_index(idx)
    files = st.load_store(p4)
    sessions = {rel[len(st.MESSAGES) + 1:-3]: ents for rel, ents in files.items() if rel.startswith(st.MESSAGES + "/")}
    stats = {"transcripts": 0, "turns": 0, "tasks": 0, "labels": {}, "matched_rows": 0}
    rows_out, tasks_out = [], []
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
                labs, _ = turn_repo_labels(turn, project, ri, tid, tr.reply_of(turn), turn["time"])
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
    if write:
        replace_source(p4, TRAIN, TRAIN_HEAD, "repo", rows_out)
        add_tasks(p4, tasks_out)
    return stats


# --- the dictionary's signals (5.3), the close hook ------------------------------------------------------

SEEN = "signals-seen.json"


def signals(p4, session=None, now=None, write=True):
    """The turn's dictionary signals: every correction and retraction not seen before, every ECHO/SUPERSEDED row
    and follow-up of `session` (every session when None), each a pending entry in vocabulary.md with `because:`
    filled. A term already there gets the new `because:` appended, never a second entry; an entry's other lines
    are never touched. Returns {signals, yielded, new_terms, appended, no_term}."""
    import migrate
    now = now or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    files = st.load_store(p4)
    seen_path = mpath(p4, SEEN)
    try:
        with open(seen_path, encoding="utf-8") as f:
            seen = set(json.load(f))
    except (OSError, ValueError):
        seen = set()
    scoped = dict(files)
    if session:
        s8 = session[:8]
        scoped = {k: v for k, v in files.items() if not k.startswith(st.MESSAGES + "/") or k == f"{st.MESSAGES}/{s8}.md"}
        # the session's earlier rows are context; only its new rows are signals: the seen set filters them below
    for f in ("corrections.md", "retractions.md"):
        scoped[f] = [e for e in files.get(f, []) if e.id not in seen]
    df, n = migrate.df_table(files, p4)
    pairs, stats = migrate.seed_dictionary(scoped, df, n, now)
    new_seen = seen | {e.id for f in ("corrections.md", "retractions.md") for e in files.get(f, [])}
    # rows: a follow-up or repeat already turned into a because: line is found again next time; the merge below
    # appends only because lines not already present, so a rerun adds nothing
    res = merge_vocabulary(p4, pairs, write=write)
    if write:
        ranker.write_atomic(seen_path, json.dumps(sorted(new_seen)))
    res.update({"signals": stats["signals"], "yielded": stats["yielded"], "no_term": len(stats["no_term"])})
    return res


def merge_vocabulary(p4, pairs, write=True):
    """Add the new terms' entries at the end of vocabulary.md and each known term's new `because:` lines after its
    last `because:`, editing nothing else."""
    path = os.path.join(st.store_dir(p4), st.VOCABULARY)
    text = st.read_text(path) if os.path.exists(path) else st.render(st.VOCABULARY, [])
    lines = text.split("\n")
    have = {}
    for e in st.parse(text, st.VOCABULARY):
        if e.head == "term":
            have[e.value.strip().lower()] = e
    new_terms, appended = [], 0
    inserts = {}
    for p in pairs:
        term = p[0][1]
        becauses = [v for k, v in p if k == "because"]
        e = have.get(term.strip().lower())
        if e is None:
            new_terms.append(p)
            have[term.strip().lower()] = None
            continue
        if e is None:
            continue
        old = set(e.all("because"))
        add = [b for b in becauses if b not in old]
        if add:
            # the line after the entry's last because: (its continuation lines included)
            end = e.line - 1
            last_b = None
            j = e.line
            while j < len(lines) and (lines[j].startswith("  ")):
                if lines[j].startswith("  because:"):
                    last_b = j
                j += 1
            at = (last_b + 1) if last_b is not None else j
            while last_b is not None and at < len(lines) and lines[at].startswith(st.CONT_PREFIX):
                at += 1
            inserts.setdefault(at, []).extend(f"  because: {b}" for b in add)
            appended += len(add)
            _ = end
    for at in sorted(inserts, reverse=True):
        lines[at:at] = inserts[at]
    out = "\n".join(lines).rstrip("\n")
    if new_terms:
        out += "\n\n" + "\n\n".join(st.format_entry(p) for p in new_terms)
    out += "\n"
    if write and (new_terms or appended):
        ranker.write_atomic(path, out)
    return {"new_terms": len(new_terms), "appended": appended, "terms": [p[0][1] for p in new_terms]}


# --- the free half of the re-exploration measure (8.5) ---------------------------------------------------

def reexploration(p4, project, slug_dirs, idx=None, k=5):
    """For every transcript turn that opened a file it later edited or cited: the tool calls and input tokens
    spent before that first open, and whether recall's top k for the prompt named the file (then the
    counterfactual cost is one Read: one call, the tokens of the turn's first API call). Returns the totals."""
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
            # relevant: edited or cited by this turn or a later one of the session
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
