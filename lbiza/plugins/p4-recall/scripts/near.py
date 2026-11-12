#!/usr/bin/env python3
"""near.py: candidates from what earlier, similar tasks used.

A task's labelled entries (the files a turn opened, cited or edited) rarely share words with its prompt, so BM25
over the prompt draws few of them: on one store (2026-11-10, the newest 400 tasks) 8% of 4,986 labelled positives,
and of the 1,339 that were new to their session, 12%. Prompts are more like each other than like file paths: the
entries the 20 earlier tasks most like a prompt used, taken from other sessions only, held 22% of those new
positives, and with BM25's, 31%.

So a task's candidates are BM25's and these, with features that say an entry came this way (`near`, `near-rank`,
`near-hit`) and how like the prompt the task that used it really was (`near-like`, `near-strong`). Measured on that
store with `p4.py eval`, held out; "loud" is the share of ordinary prompts the fitted model would print for:

                                      usable tasks  r-precision  recall@20  precision  top-5 hit  loud
  BM25 candidates alone                     89         0.023       0.140      0.093      0.30     0.22
  with these, and no feature (prototype)   150         0.016       0.133      0.080      0.27
  with these, near/rank/hit only           146         0.035       0.217      0.107      0.42     0.70
  with these and the likeness features     147         0.036       0.225      0.129      0.37     0.00
  the same, own session included           158         0.115       0.299      0.242      0.56     0.00

The candidates alone do harm: the ranker has to be told where an entry came from. Without the likeness features the
twenty nearest tasks count the same however far they are, and the model prints for most ordinary prompts. The last
row is not used. What a session opened a turn ago is already in its context: recalling it scores well and
tells the session nothing, so only other sessions' tasks count (`recall.near.same_session` turns that on).

The memory is `models/near.json` (a cache, ignored by git): every labelled task's time, session, prompt tokens and
positive entries, written by a training round and read by a query, which never builds it (a message's hook has a
300 ms budget). A task only ever sees tasks dated before it.
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
NEIGHBOURS = 20               # earlier tasks whose entries are taken
MAX = 100                     # entries added to a task's candidates, the highest scored first
SAME_SESSION = False          # the session's own earlier tasks too (module docstring: off)


def configure(p4):
    import p4conf
    p4conf.configure(globals(), p4, "recall.near", {"on": "ON", "neighbours": "NEIGHBOURS", "max": "MAX",
                                                    "same_session": "SAME_SESSION"}, write=False)


def path(p4):
    return p4conf.sub(p4, "models", FILE)


def build(p4, idx, labels=None, write=True):
    """The memory from the store's tasks and training labels: {"tasks": [[time, session, tokens, [entry ids]]]},
    oldest first, each task's positives that the index holds. Written to models/near.json when `write`."""
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
    """The memory a training round left, or None (no round yet, or another version)."""
    try:
        with open(path(p4), encoding="utf-8") as f:
            mem = json.load(f)
    except (OSError, ValueError):
        return None
    return prepare(mem) if isinstance(mem, dict) and mem.get("version") == VERSION else None


def entries(mem, text, when="", session="", same_session=None):
    """{entry id: score} from the NEIGHBOURS tasks dated before `when` whose prompts are most like `text`: a task's
    likeness is the idf of the words it shares with the prompt over the root of its own length, and an entry's
    score the sum over the tasks that used it. Empty `when` means now (every task counts)."""
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
    # NEIGHBOURS nearest are taken however far they are, and without this a faint likeness looks like a strong one
    # (a word no task ever used is as rare as a word can be: a prompt made of such words is like nothing)
    whole = sum(idf.get(w, mem["rarest"]) for w in mine) / math.sqrt(1 + len(mine)) or 1.0
    out = Scores()
    for sc, k in scored[:NEIGHBOURS]:
        for e in mem["rows"][k][3]:
            out[e] = out.get(e, 0.0) + sc
            out.like[e] = max(out.like.get(e, 0.0), min(1.0, sc / whole))
    return out


class Scores(dict):
    """{entry id: score}, with `like`: {entry id: how like the prompt the most similar task that used it was, 0..1}."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.like = {}


def id_index(docs):
    """{entry id: doc index}, read off the index's rows where it has them, so a query decodes no doc for it."""
    rows, fields = getattr(docs, "rows", None), getattr(docs, "fields", None)
    if rows is not None and fields:
        k = fields.index("id")
        return {r[k]: i for i, r in enumerate(rows)}
    return {d["id"]: i for i, d in enumerate(docs)}


def extend(docs, id_at, cand, got, allowed):
    """(candidates with the near entries BM25 did not draw appended, {candidate position: (score over the best,
    1 / (1 + rank))} for every candidate that is a near entry). `got` is entries()'s result, `id_at` {entry id: doc
    index}, `allowed(doc index)` says an entry may be a candidate at all (not superseded, dated before the task)."""
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
