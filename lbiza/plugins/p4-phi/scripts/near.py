#!/usr/bin/env python3
"""near.py: candidates from what earlier, similar tasks used.

A task's repo labels are on the files a turn opened, cited or edited. They rarely share words with its prompt, so
BM25 over the prompt draws few of them, while prompts are more like each other than like file paths. near.py
adds to a task's candidates the documents that the NEIGHBOURS earlier tasks most like its prompt used, at most MAX
of them. Three features tell the ranker that a document came this way: `near`, `near-rank` and `near-hit`. Without
them the added candidates do harm. Two more say how like the prompt the task that used a document was: `near-like`
and `near-strong`.

It is on while p4.json `recall.near.on` is true, as it is by default. A training round then adds these documents to
the candidates of each task whose candidates BM25 draws from the whole index and of each silence task, and the
model it writes lists `near` among its features. A query adds them only for a served model that lists `near`, and
only after a round has written the memory. Only other sessions' tasks count unless `recall.near.same_session` is
true: what a session opened a turn ago is already in its context, so retrieving it scores well and tells the
session nothing.

The memory is `phi/models/near.json`, a cache git ignores. It holds every labelled task's time, session, prompt
words and positive documents. A training round writes it, and a query only reads it: building it would not fit the
time budget stated at `h_recall` in hook.py. A task only ever sees tasks dated before it.
"""

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import ranker  # noqa: E402

FILE = "near.json"
VERSION = 1
ON = True
NEIGHBOURS = 20               # earlier tasks whose documents are taken
MAX = 100                     # documents added to a task's candidates, the highest scored first
SAME_SESSION = False          # the session's own earlier tasks too; the module docstring says why not


def configure(p4):
    import p4conf
    p4conf.configure(globals(), p4, "recall.near", {"on": "ON", "neighbours": "NEIGHBOURS", "max": "MAX",
                                                    "same_session": "SAME_SESSION"}, write=False)


def path(p4):
    return p4conf.sub(p4, "models", FILE)


def build(p4, idx, labels=None, write=True):
    """The memory from the store's tasks and its training labels, or from `labels` in their place:
    {"version": VERSION, "tasks": [[time, session, tokens, [document ids]]]}, oldest first, each task with its
    positives that the index holds. Written to phi/models/near.json when `write`, and returned as prepare() leaves
    it."""
    import labels as lb
    ids = {d["id"] for d in idx["docs"]}
    tasks = lb.read_tasks(p4)
    pos = {}
    for r in (lb.training_labels(p4, idx) if labels is None else labels):
        if r["label"] and r["entry"] in ids and r["task"] in tasks:
            pos.setdefault(r["task"], set()).add(r["entry"])
    rows = []
    for t in sorted(pos, key=lambda t: (tasks[t].get("time", ""), t)):
        toks = sorted(set(ranker.tokens(tasks[t].get("text", ""))))
        if toks:
            rows.append([tasks[t].get("time", ""), (tasks[t].get("session") or "")[:8], " ".join(toks), sorted(pos[t])])
    mem = {"version": VERSION, "tasks": rows}
    if write:
        os.makedirs(os.path.dirname(path(p4)), exist_ok=True)
        ranker.write_atomic(path(p4), json.dumps(mem, separators=(",", ":"), ensure_ascii=False))
    return prepare(mem)


def prepare(mem):
    """The memory with its token sets and the idf of a prompt word among the tasks."""
    rows = [(t, s, frozenset(toks.split()), pos) for t, s, toks, pos in mem.get("tasks", [])]
    df = {}
    for _t, _s, toks, _p in rows:
        for w in toks:
            df[w] = df.get(w, 0) + 1
    n = max(1, len(rows))
    return {"rows": rows, "idf": {w: math.log(1 + n / c) for w, c in df.items()}, "rarest": math.log(1 + n)}


def load(p4):
    """The memory a training round left; None when no round has written it or it is of another version."""
    try:
        with open(path(p4), encoding="utf-8") as f:
            mem = json.load(f)
    except (OSError, ValueError):
        return None
    return prepare(mem) if isinstance(mem, dict) and mem.get("version") == VERSION else None


def entries(mem, text, when="", session="", same_session=None):
    """{document id: score} from the NEIGHBOURS tasks dated before `when` whose prompts are most like `text`: a task's
    likeness is the idf of the words it shares with the prompt over the root of its own length, and a document's
    score the sum over the tasks that used it. An empty `when` means now, when every task counts. The session's own
    tasks are left out unless `same_session`, which defaults to SAME_SESSION. The result is a `Scores`."""
    if not mem or not mem["rows"]:
        return {}
    same_session = SAME_SESSION if same_session is None else same_session
    mine = set(ranker.tokens(text or ""))
    if not mine:
        return {}
    idf, sess = mem["idf"], (session or "")[:8]
    scored = []
    for k, (t, s, toks, _pos) in enumerate(mem["rows"]):
        if when and t[:16] >= when[:16]:
            break                                # oldest first: nothing later is earlier
        if not same_session and sess and s == sess:
            continue
        shared = mine & toks
        if shared:
            scored.append((sum(idf.get(w, 0.0) for w in shared) / math.sqrt(1 + len(toks)), k))
    scored.sort(key=lambda x: (-x[0], x[1]))
    # what a task identical to the prompt would score: the measure of how like it a neighbour really is. The
    # NEIGHBOURS nearest are taken however far they are, and without this a faint likeness looks like a strong one.
    # A word no task ever used counts as rare as a word can be, so a prompt made of such words is like nothing.
    whole = sum(idf.get(w, mem["rarest"]) for w in mine) / math.sqrt(1 + len(mine)) or 1.0
    out = Scores()
    for sc, k in scored[:NEIGHBOURS]:
        for e in mem["rows"][k][3]:
            out[e] = out.get(e, 0.0) + sc
            out.like[e] = max(out.like.get(e, 0.0), min(1.0, sc / whole))
    return out


class Scores(dict):
    """{document id: score}, with `like`: {document id: x}, where x, from 0 to 1, is how like the prompt the most
    similar task that used that document was."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.like = {}


def id_index(docs):
    """{document id: position in docs}, read off the index's rows where it has them, so a query decodes no document
    for it."""
    rows, fields = getattr(docs, "rows", None), getattr(docs, "fields", None)
    if rows is not None and fields:
        k = fields.index("id")
        return {r[k]: i for i, r in enumerate(rows)}
    return {d["id"]: i for i, d in enumerate(docs)}


def extend(docs, id_at, cand, got, allowed):
    """The candidates with at most MAX near documents that BM25 did not draw appended, and {candidate position:
    features} for every candidate that is a near document. A near document's features are its score over the best
    and `1 / (1 + rank)`, then its likeness when `got` is a `Scores`. `got` is entries()'s result and `id_at` is
    {document id: position in docs}.
    `allowed(position in docs)` says whether a document may be a candidate at all: a query refuses a superseded one,
    and training one the task could not have been shown."""
    if not got:
        return list(cand), {}
    have = set(cand)
    order = sorted(got, key=lambda e: (-got[e], e))
    rank = {e: k for k, e in enumerate(order)}
    more = [id_at[e] for e in order if e in id_at and id_at[e] not in have and allowed(id_at[e])][:MAX]
    out = list(cand) + more
    top = got[order[0]] or 1.0
    like = getattr(got, "like", None)
    feats = {}
    for k, i in enumerate(out):
        e = docs[i]["id"]
        if e in got:
            feats[k] = (got[e] / top, 1.0 / (1 + rank[e])) + ((like.get(e, 0.0),) if like is not None else ())
    return out, feats
