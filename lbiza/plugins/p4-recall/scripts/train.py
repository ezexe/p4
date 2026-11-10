#!/usr/bin/env python3
"""train.py: the ranker's rounds (fresh-marketplace.md 5.5, 5.6) and the dictionary's check (5.3).

  train [--if-owed]   fit on every label weighted by its source, evaluate held out, promote past the floor, append
                      models/eval.tsv; --if-owed returns at once unless >= 10 labels landed since the last round and
                      the last round is older than an hour (the async Stop hook's road)
  eval                the same numbers, nothing written
  dictionary check    every vocabulary entry's two tests; a failing entry is set `status: off` (an owner's entry is
                      listed, never changed)

How a task becomes examples. A task (models/tasks.tsv) has a text and a time; its candidates are the indexed entries
dated no later than the task (or undated), never its own session's message rows, scored by BM25 on the task's
terms; the top CANDIDATES of them (every one for a pool task, as `pick_model.py` read every barrier row) are
featurized by `ranker.candidate_features`, and a candidate is positive when a label names it. Evaluation is
leave-one-task-out for up to LOO_MAX tasks and grouped k-fold above it, `pick_model.py eval`'s numbers:
R-precision, recall@20 and the precision of the threshold's picks, so the 0.379 baseline is comparable.

Weights per source (5.5): store+edited 1.0, pool 0.7, short 1.0, usage 0.3 (until 8.1's agreement test raises
it), miss 1.0, store 0.5 (the raw history labels, which agree with teachers at 0.50-0.53), repo as the row says.

The silence tasks. Every labelled task has an answer in the store, so a ranker fit on them alone never learns what
no match looks like: its features are relative (BM25 over the top candidate's, the rank), so the top candidate of
an ordinary message scores like the top candidate of a real one, and the trained road printed lines for 88% of the
suite's general prompts (the no-ranker road: 0%). A silence task is an ordinary message with no positive: its
candidates are what `p4.py query` would hand the ranker (the top CANDIDATES of BM25 over the whole index), every one
a negative. They come from models/silent.jsonl when the store has one, else from the plugin's silent-prompts.jsonl
(the suite's general prompts of its train split; its test split stays held out). They are always in the training
half, never a held-out fold, and the threshold is still chosen on the labelled tasks alone.
"""

import datetime
import json
import math
import os
import random
import re
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import labels as lb  # noqa: E402
import ranker  # noqa: E402
import store as st  # noqa: E402

SOURCE_WEIGHT = {"store+edited": 1.0, "pool": 0.7, "short": 1.0, "usage": 0.3, "miss": 1.0, "store": 0.5,
                 "repo": 1.0, "silent": 1.0}
SILENT = "silent.jsonl"                                   # models/silent.jsonl: {"prompt": ...} per line
SILENT_DEFAULT = os.path.join(HERE, "silent-prompts.jsonl")
CANDIDATES = 200
POOL_CANDIDATES = 0           # 0: every eligible entry, as the old pools' barrier rows
TRAIN_NEG = 60                # negatives kept per task when fitting (the top of BM25), so a round stays in seconds
LOO_MAX = 40
FOLDS = 5
FLOOR_DROP = 0.02
MIN_PRECISION = 0.6
FIRST_FLOOR = 0.36            # 5.6: the first round after migration, from pool labels alone, on AudioPlugin-p4
OWED_LABELS = 10
OWED_AGE_S = 3600
MAX_TASKS = 400               # newest tasks a round fits on, beyond the pool and edited ones (every one kept)
EVAL_HEAD = "round\ttime\tlabels\ttasks\tper_source\tr_precision\trecall20\tprecision\tthreshold\tbaseline\t" \
            "short\trepo\tdictionary\tpromoted\twhy\n"
NONSTORE_FILES = ("messages",)


# --- examples ----------------------------------------------------------------------------------------------

def eligible(doc, task):
    """An entry a task could have been shown: dated no later than the task (or undated), not a row of its own
    session's messages."""
    t = doc.get("time") or ""
    if t and task["time"] and t[:16] > task["time"][:16]:
        return False
    if doc["file"] == "messages" and task.get("session") and task["session"][:8] in doc["path"]:
        return False
    return True


def task_examples(idx, task, positives, limit=None, files=None, docs_by=None):
    """(xs, ys, cand doc indices, bm25 scores) for one task: features of its candidates and their 0/1 labels."""
    import p4 as cli
    limit = CANDIDATES if limit is None else limit
    terms = list(dict.fromkeys(ranker.tokens(task["text"])))
    if not terms:
        return [], [], [], []
    docs = idx["docs"]
    if files is None:
        scores = cli.bm25_scores(idx, terms, {})
        idf, avgdl = cli.idf_map(idx, terms), idx["avgdl"]
    else:
        # a pool's candidates are the store's entries alone, scored with the store's own statistics, as the old
        # barrier was: the idf of a term among the rulings, corrections and facts, not among every message and file
        sub = sub_corpus(idx, files)
        idf = {t: sub["idf"][t] for t in terms if t in sub["idf"]}
        avgdl = sub["avgdl"]
        tset = set(terms)
        scores = {}
        for i in sub["ids"]:
            d = docs[i]
            tf = {t: c for t, c in sub["tf"][i].items() if t in tset}
            if tf:
                scores[i] = ranker.bm25_tf(terms, tf, d["dl"], idf, avgdl)
    pool = [i for i in (scores if limit else (sub_corpus(idx, files)["ids"] if files else range(len(docs))))
            if (files is None or docs[i]["file"] in files) and eligible(docs[i], task)]
    pool.sort(key=lambda i: (-scores.get(i, 0.0), i))
    cand = pool[:limit] if limit else pool
    mem, feats = (docs_by or {}).get("near") if files is None else None, None
    if mem:
        # near.py: the entries earlier, similar tasks of other sessions used join BM25's, with a feature saying so
        import near
        got = near.entries(mem, task["text"], task.get("time") or "", task.get("session") or "")
        cand, feats = near.extend(docs, docs_by["id_at"], cand, got, lambda i: eligible(docs[i], task))
    if not cand:
        return [], [], [], []
    heads = (docs_by or {}).get("head140", {})
    cds = [{"file": docs[i]["file"], "kind": docs[i]["kind"], "state": docs[i]["state"], "time": docs[i]["time"],
            "toks": docs[i]["toks"].split(), "head": heads.get(docs[i]["id"]) or docs[i]["head"].split(),
            "dl": docs[i]["dl"], "fkind": docs[i].get("fkind")} for i in cand]
    sc = [scores.get(i, 0.0) for i in cand]
    xs, _, _ = ranker.candidate_features(terms, cds, idf, avgdl, task["time"] or "", scores=sc,
                                         extra={"near": feats} if feats is not None else None)
    ys = [1 if docs[i]["id"] in positives else 0 for i in cand]
    return xs, ys, cand, sc


def silent_prompts(p4):
    """The ordinary messages a round trains silence on: models/silent.jsonl, else the plugin's default list."""
    path = os.path.join(p4, "models", SILENT)
    if not os.path.exists(path):
        path = SILENT_DEFAULT
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                p = (r.get("prompt") if isinstance(r, dict) else r) or ""
                if isinstance(p, str) and p.strip():
                    out.append(p.strip())
    except OSError:
        return []
    return out


def silent_sets(idx, prompts, now, mem=None, id_at=None):
    """One all-negative set per ordinary message, its candidates and features exactly as p4.query builds them for
    the ranker road (BM25 over the whole index, the superseded out, the top CANDIDATES, then near.py's entries when
    the round uses them: a near entry on an ordinary message has to learn silence too)."""
    import p4 as cli
    docs = idx["docs"]
    gone = cli.superseded_ids(idx, now)
    out = []
    for text in prompts:
        terms = list(dict.fromkeys(ranker.tokens(text)))
        if not terms:
            continue
        scores = cli.bm25_scores(idx, terms, {})
        cand = [i for i in sorted(scores, key=lambda i: (-scores[i], i)) if docs[i]["id"] not in gone][:CANDIDATES]
        feats = None
        if mem:
            import near
            cand, feats = near.extend(docs, id_at, cand, near.entries(mem, text), lambda i: docs[i]["id"] not in gone)
        if not cand:
            continue
        idf = cli.idf_map(idx, terms)
        cds = [{"file": docs[i]["file"], "kind": docs[i]["kind"], "state": docs[i]["state"], "time": docs[i]["time"],
                "toks": docs[i]["toks"].split(), "head": docs[i]["head"].split(), "dl": docs[i]["dl"],
                "fkind": docs[i].get("fkind")} for i in cand]
        sc = [scores.get(i, 0.0) for i in cand]
        xs, _, _ = ranker.candidate_features(terms, cds, idf, idx["avgdl"], now, scores=sc,
                                             extra={"near": feats} if feats is not None else None)
        w = SOURCE_WEIGHT["silent"]
        out.append({"task": "silent:" + st.sha8(text), "xs": xs, "ys": [0] * len(cand), "w": [w] * len(cand),
                    "files": [docs[i]["path"] for i in cand], "bm25": sc, "n_pos": 0, "source": "silent",
                    "missed": False, "kind": "silent", "time": now, "sources": ["silent"],
                    "cand_ids": [docs[i]["id"] for i in cand]})
    return out


def head_tokens(p4):
    """{entry id: tokens of its head value cut at 140 characters, with repeats}: what an old pool child read of an
    entry, the `head-bm25` feature's text as pick_model.py computed it."""
    out = {}
    for f, ents in st.load_store(p4).items():
        if f.startswith(st.MESSAGES + "/"):
            continue
        for e in ents:
            out[e.id] = ranker.tokens(st.collapse(e.value)[:140])
    return out


def sub_corpus(idx, files):
    """{ids, idf, avgdl, tf} over the docs of `files`, cached on the index. A doc's term frequencies come back from
    the postings (the index keeps only the distinct terms on a doc)."""
    key = "_sub:" + ",".join(sorted(files))
    if key in idx:
        return idx[key]
    docs = idx["docs"]
    ids = [i for i, d in enumerate(docs) if d["file"] in files]
    want = set(ids)
    tf = {i: {} for i in ids}
    for t in list(idx["post"]):
        p = st.postings(idx, t)
        for j in range(0, len(p), 2):
            if p[j] in want:
                tf[p[j]][t] = p[j + 1]
    for i, htf in idx.get("_held", {}).items():
        if i in want:
            tf[i] = dict(htf)
    df = {}
    for i in ids:
        for t in tf[i]:
            df[t] = df.get(t, 0) + 1
    n = len(ids)
    out = {"ids": ids, "idf": {t: ranker.idf_of(c, n) for t, c in df.items()},
           "avgdl": sum(docs[i]["dl"] for i in ids) / max(1, n), "tf": tf}
    idx[key] = out
    return out


def with_held(idx, p4):
    """The index with the store's held entries (store.held_docs: freed, spent, expired) appended after its docs, for
    pool tasks alone: they carry no postings, so BM25 over the index never draws them, and sub_corpus takes their
    term frequencies from `_held`. The caller's index is left as it was."""
    held = st.held_docs(p4)
    if not held:
        return idx
    out = {k: v for k, v in idx.items() if not k.startswith("_sub:")}
    base = len(idx["docs"])
    out["docs"] = list(idx["docs"]) + held
    out["_held"] = {base + k: d["_tf"] for k, d in enumerate(held)}
    return out


def pool_like(r):
    """A pool label, or a teacher's edit of a pool task (its note says `from:pool`): drawn from the store's entries
    alone, as the old barrier was, so a task's edited set and its raw set share their candidates."""
    return r["source"] == "pool" or (r["source"] == "store+edited" and "from:pool" in (r.get("note") or ""))


def build_sets(p4, idx=None, sources=None, max_tasks=None, rows=None, now=None, keep_near=False):
    """[{task, xs, ys, w, files, bm25, n_pos, source}] for every task with at least one positive that is indexed,
    then the silence tasks (source `silent`, no positive) unless `sources` leaves them out.

    Each task's positives are its labels with label 1 (weighted by source); a label 0 is a hard negative: kept in
    the candidates at its weight even when BM25 would not have drawn it. `rows` stands in for the training labels
    (raw_vs_edited's two label sets)."""
    if idx is None:
        idx, _ = st.ensure_index(p4)
    tasks = lb.read_tasks(p4)
    given = rows
    rows = lb.training_labels(p4, idx) if rows is None else rows
    if sources:
        rows = [r for r in rows if r["source"] in sources]
    if any(pool_like(r) for r in rows):
        idx = with_held(idx, p4)
    by_task = {}
    for r in rows:
        by_task.setdefault(r["task"], []).append(r)
    ids = {d["id"]: i for i, d in enumerate(idx["docs"])}
    store_files = set(st.STORE_FILES)
    extra = {"head140": head_tokens(p4)}
    import near
    near.configure(p4)
    if near.ON:
        # the memory of what earlier tasks used: built from this round's own labels, and kept for the queries only
        # when a writing round built it from the store's whole training set (not an eval, one source, or stand-ins)
        extra["near"] = near.build(p4, idx, labels=rows, write=keep_near and given is None and not sources)
        extra["id_at"] = near.id_index(idx["docs"])
    out = []
    order = sorted(by_task, key=lambda t: (tasks.get(t, {}).get("time", ""), t), reverse=True)
    keep_all = {t for t in order if any(r["source"] in ("pool", "store+edited") for r in by_task[t])}
    n_other = 0
    for tid in order:
        task = tasks.get(tid)
        if not task:
            continue
        if tid not in keep_all:
            n_other += 1
            if n_other > (MAX_TASKS if max_tasks is None else max_tasks):
                continue
        labs = by_task[tid]
        pos = {}
        for r in labs:
            if r["label"] and r["entry"] in ids:
                pos[r["entry"]] = max(pos.get(r["entry"], 0.0), r["weight"])
        if not pos:
            continue
        is_pool = all(pool_like(r) for r in labs)
        limit = POOL_CANDIDATES if is_pool else CANDIDATES
        files = store_files if is_pool else None
        xs, ys, cand, sc = task_examples(idx, task, pos, limit=limit, files=files, docs_by=extra)
        if not xs or not sum(ys):
            out.append({"task": tid, "xs": [], "ys": [], "n_pos": len(pos), "source": labs[0]["source"],
                        "missed": True, "kind": task.get("kind", "")})
            continue
        # a task's drawn negatives weigh what its labels weigh, so a source's weight scales the task, never the
        # balance of positives against negatives within it (ranker.fit balances those)
        tw = max(pos.values())
        ws = [pos[idx["docs"][i]["id"]] if y else tw for i, y in zip(cand, ys)]
        neg_w = {r["entry"]: r["weight"] for r in labs if not r["label"]}
        for k, i in enumerate(cand):
            if idx["docs"][i]["id"] in neg_w:
                ws[k] = max(ws[k], neg_w[idx["docs"][i]["id"]] * 2)   # a stated negative counts more than a drawn one
        out.append({"task": tid, "xs": xs, "ys": ys, "w": ws, "files": [idx["docs"][i]["path"] for i in cand],
                    "bm25": sc, "n_pos": len(pos), "source": labs[0]["source"], "missed": False,
                    "kind": task.get("kind", ""), "time": task.get("time", ""), "pool_like": is_pool,
                    "sources": sorted({r["source"] for r in labs}),
                    "cand_ids": [idx["docs"][i]["id"] for i in cand]})
    if out and (not sources or "silent" in sources):
        out.extend(silent_sets(idx, silent_prompts(p4), now or datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                               mem=extra.get("near"), id_at=extra.get("id_at")))
    return out


def fit_sets(sets, seed=0):
    ex, ws = [], []
    for s in sets:
        if s["missed"]:
            continue
        keep = trim(s)
        for k in keep:
            ex.append((s["xs"][k], s["ys"][k]))
            ws.append(s["w"][k])
    return ranker.fit(ex, weights=ws, seed=seed) if ex else {}


def trim(s):
    """The examples of one task a round fits on: every positive, and TRAIN_NEG of its negatives drawn at random
    (seeded by the task, so a round is deterministic); a pool task keeps every candidate, as pick_model.py fit on
    every barrier row. The negatives were once the TRAIN_NEG BM25 ranked highest: with the positives kept wherever
    BM25 put them, that taught the ranker a high BM25 is a negative (on a 97-pool store its bm25 weight fit at -1.05,
    against +0.28 with every candidate) and halved its held-out R-precision."""
    if s.get("source") == "silent" or ((s.get("source") == "pool" or s.get("pool_like")) and POOL_CANDIDATES == 0):
        return range(len(s["ys"]))
    negs = [k for k in range(len(s["ys"])) if not s["ys"][k]]
    if len(negs) > TRAIN_NEG:
        negs = random.Random(zlib.crc32(str(s.get("task", "")).encode("utf-8"))).sample(negs, TRAIN_NEG)
    return sorted([k for k in range(len(s["ys"])) if s["ys"][k]] + negs)


def scored(w, s):
    return [ranker.score(w, x) for x in s["xs"]]


# --- evaluation ------------------------------------------------------------------------------------------

def folds(sets):
    n = len(sets)
    if n <= LOO_MAX:
        return [[k] for k in range(n)]
    order = sorted(range(n), key=lambda k: (sets[k].get("time", ""), k))
    return [order[f::FOLDS] for f in range(FOLDS)]


def evaluate(sets, per_file=ranker.PER_FILE, quiet=True):
    """Held-out numbers over the sets: {r-precision, recall@20, precision, f1, baseline, n, per-subset, rows}."""
    silent = [s for s in sets if s.get("source") == "silent"]
    live = [s for s in sets if not s["missed"] and s.get("source") != "silent"]
    missed = [s for s in sets if s["missed"]]
    if len(live) < 3:
        return None
    rows = {}
    for fold in folds(live):
        held = set(fold)
        train = [s for k, s in enumerate(live) if k not in held]
        w = fit_sets(train + silent)      # the silence tasks train every fold and are held out of none
        t = ranker.best_threshold([(s["files"], s["ys"], scored(w, s)) for s in train], per_file, MIN_PRECISION)
        for k in fold:
            s = live[k]
            sc = scored(w, s)
            m = ranker.metrics(s["ys"], sc, ranker.select(s["files"], sc, t, per_file))
            n = sum(s["ys"])
            bm = s["bm25"]
            base = ranker.metrics(s["ys"], bm, sorted(range(len(bm)), key=lambda i: (-bm[i], i))[:n])
            m["threshold"] = t
            m["top5"] = sum(s["ys"][i] for i in sorted(range(len(sc)), key=lambda i: (-sc[i], i))[:5]) > 0
            # R-precision counts the labelled entries BM25 never drew as misses, as the old pools did; the baseline
            # ranks the same drawn candidates, so it counts them the same way, or it reads up to n_pos / n too high
            drawn = n / max(n, s["n_pos"])
            m["r-precision"] = m["r-precision"] * drawn
            m["baseline"] = base["r-precision"] * drawn
            rows[s["task"]] = m
    out = summarize(list(rows.values()), len(missed))
    out["rows"] = rows
    if silent:
        out["silent"] = {"n": len(silent)}
    for name, keep in (("pool", lambda s: s["source"] == "pool"), ("repo", lambda s: "repo" in s.get("sources", [])),
                       ("history", lambda s: s["source"] == "store")):
        sub = [rows[s["task"]] for s in live if keep(s) and s["task"] in rows]
        if sub:
            out[name] = summarize(sub, 0)
    return out


def summarize(ms, missed):
    n = len(ms) + missed
    return {"n": len(ms), "missed": missed,
            "r-precision": sum(m["r-precision"] for m in ms) / max(1, n),
            "recall@20": sum(m["recall@20"] for m in ms) / max(1, n),
            "precision": ranker.mean(ms, "precision"), "f1": ranker.mean(ms, "f1"),
            "baseline": sum(m.get("baseline", 0.0) for m in ms) / max(1, n),
            "top5": sum(1 for m in ms if m.get("top5")) / max(1, len(ms)),
            "threshold": ranker.mean(ms, "threshold") if ms else 0.0}


# --- the short-turn subset (5.4), free -------------------------------------------------------------------

def short_subset(p4, idx=None, held_sessions=3):
    """On the newest `held_sessions` sessions' completed short rows: whether the history line's reading (the last
    completed `addressed:` of that token in an earlier row) matches the held-out row's `addressed:` by the
    resemblance rule. {n, shown, right, rate}."""
    files = st.load_store(p4)
    sessions = []
    for rel, ents in files.items():
        if rel.startswith(st.MESSAGES + "/") and ents:
            sessions.append((max(e.time for e in ents), rel))
    sessions.sort()
    held = {rel for _, rel in sessions[-held_sessions:]}
    seen = {}
    for _, rel in sessions:
        if rel in held:
            continue
        for e in files[rel]:
            tok = st.norm_token(st.unquote(e.fields.get("fingerprint", e.value)))
            if tok and len(tok.split()) <= st.SHORT_WORDS and st.completed(e):
                seen.setdefault(tok, []).append(e)
    n = shown = right = 0
    for rel in sorted(held):
        for e in files[rel]:
            tok = st.norm_token(st.unquote(e.fields.get("fingerprint", e.value)))
            if not tok or len(tok.split()) > st.SHORT_WORDS or not st.completed(e):
                continue
            n += 1
            prior = [x for x in seen.get(tok, []) if x.time <= e.time]
            if len(prior) >= st.KNOWN_SHORT_MIN - 1 and prior:
                shown += 1
                a = set(st.norm_token(prior[-1].fields.get("addressed", "")).split())
                b = set(st.norm_token(e.fields.get("addressed", "")).split())
                right += st.resembles(b, a) or (len(a & b) / max(1, len(a | b)) >= 0.3)
            seen.setdefault(tok, []).append(e)
    return {"n": n, "shown": shown, "right": right, "rate": right / shown if shown else 0.0}


# --- the round -------------------------------------------------------------------------------------------

def eval_rows(p4):
    path = os.path.join(p4, "models", "eval.tsv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    if not lines:
        return []
    head = lines[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in lines[1:] if l.strip()]


def last_promoted(p4):
    for r in reversed(eval_rows(p4)):
        if r.get("promoted") == "promoted":
            return r
    return None


def owed(p4, now_s=None):
    """(owed?, why): >= OWED_LABELS labels landed since the last round, and the last round older than an hour; or a
    dependency was installed or updated since the last round (its entries are new candidates), whatever the age."""
    now_s = now_s or time.time()
    rows = eval_rows(p4)
    n = lb.count_labels(p4)
    if not rows:
        return (n >= 1, f"no round yet, {n} labels")
    last = rows[-1]
    try:
        before = int(last.get("labels", "0"))
    except ValueError:
        before = 0
    path = os.path.join(p4, "models", "eval.tsv")
    age = now_s - os.path.getmtime(path)
    try:                                   # deps.py: a package installed or updated after the last round
        import deps
        if deps.changed_at(p4) > os.path.getmtime(path):
            return True, "a dependency was installed or updated since the last round"
    except (ImportError, OSError, ValueError):
        pass
    if n - before < OWED_LABELS:
        return False, f"{n - before} labels since the last round (need {OWED_LABELS})"
    if age < OWED_AGE_S:
        return False, f"the last round is {int(age)} s old (need {OWED_AGE_S})"
    return True, f"{n - before} new labels, last round {int(age)} s old"


def configure(p4):
    """recall.train of the store's p4.json over the training constants (read, never written, here)."""
    import p4conf
    p4conf.configure(globals(), p4, "recall.train", {
        "candidates": "CANDIDATES", "train_neg": "TRAIN_NEG", "folds": "FOLDS", "floor_drop": "FLOOR_DROP",
        "min_precision": "MIN_PRECISION", "first_floor": "FIRST_FLOOR", "owed_labels": "OWED_LABELS",
        "owed_age_s": "OWED_AGE_S", "max_tasks": "MAX_TASKS"}, write=False)


def run_round(p4, write=True, now=None, idx=None, sources=None, quiet=False, dictionary=True):
    """One round: build the sets, evaluate held out, fit on all, decide promotion by the floor. Returns the
    eval row as a dict; writes models/ranker.json (only when promoted) and appends models/eval.tsv when `write`."""
    now = now or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    configure(p4)
    if idx is None:
        idx, _ = st.ensure_index(p4)
    t0 = time.time()
    # 5.2 step 3: when the teacher's edits exist, they must score at or above the raw labels on held-out raw labels;
    # a round that finds them below holds their batches (written only by `train`), so the sets below leave them out
    cmp = raw_vs_edited(p4, idx) if has_edited(p4) else None
    if cmp and cmp.get("ok") is False and write:
        hold_batches(p4, cmp["batches"], f"edited {cmp['edited']:.3f} below raw {cmp['raw']:.3f} on held-out raw "
                                         f"labels ({now})")
    sets = build_sets(p4, idx, sources, now=now, keep_near=write)
    ev = evaluate(sets)
    per_source = {}
    for r in lb.training_labels(p4, idx):
        per_source[r["source"]] = per_source.get(r["source"], 0) + 1
    short = short_subset(p4, idx)
    dict_counts = {"on": 0, "off": 0, "fixed": 0, "harmed": 0}
    newly_harmed = []
    if dictionary:
        dres = dictionary_check(p4, idx=idx, write=write)
        dict_counts = dres["counts"]
        newly_harmed = [r for r in dres["entries"] if r["harmed"] and r["status_after"] == "on"]
    prev = last_promoted(p4)
    why, promote = [], True
    if ev is None:
        promote, why = False, ["fewer than 3 labelled tasks"]
    else:
        if prev:
            try:
                floor = float(prev.get("r_precision", "0")) - FLOOR_DROP
            except ValueError:
                floor = 0.0
            if ev["r-precision"] < floor:
                promote = False
                why.append(f"r-precision {ev['r-precision']:.3f} below the floor {floor:.3f}")
            try:
                ps = float(prev.get("short", "0").split("/")[0] or 0)
            except ValueError:
                ps = 0.0
            if short["rate"] + 1e-9 < ps:
                promote = False
                why.append(f"short-turn subset {short['rate']:.3f} below the last round's {ps:.3f}")
        if prev is None:
            # 5.6: the first round after migration must reach FIRST_FLOOR from the imported pool labels alone
            pool_sets = [x for x in sets if x["source"] == "pool" and set(x.get("sources", ["pool"])) == {"pool"}]
            if len(pool_sets) >= 3:
                pev = evaluate(pool_sets) if sources != {"pool"} else ev
                first_pool = pev["r-precision"]
                if first_pool < FIRST_FLOOR:
                    promote = False
                    why.append(f"first round: pool labels alone reach r-precision {first_pool:.3f}, below "
                               f"{FIRST_FLOOR}")
        if ev["precision"] < MIN_PRECISION:
            promote = False
            why.append(f"precision at threshold {ev['precision']:.3f} below {MIN_PRECISION}")
        if newly_harmed:
            promote = False
            why.append(f"{len(newly_harmed)} dictionary entries harm working messages and are still on")
    row = {"round": str(int(prev["round"]) + 1 if prev and prev.get("round", "").isdigit() else
                        len(eval_rows(p4))),
           "time": now, "labels": str(lb.count_labels(p4)), "tasks": str(len(sets)),
           "per_source": ",".join(f"{k}:{v}" for k, v in sorted(per_source.items())),
           "r_precision": f"{ev['r-precision']:.4f}" if ev else "", "recall20": f"{ev['recall@20']:.4f}" if ev else "",
           "precision": f"{ev['precision']:.4f}" if ev else "", "threshold": "", "baseline":
               f"{ev['baseline']:.4f}" if ev else "",
           "short": f"{short['rate']:.4f}/{short['right']}/{short['shown']}/{short['n']}",
           "repo": f"{ev['repo']['top5']:.4f}/{ev['repo']['n']}" if ev and "repo" in ev else "",
           "dictionary": ",".join(f"{k}:{v}" for k, v in dict_counts.items()),
           "promoted": "promoted" if promote else "kept old", "why": "; ".join(why) or "past the floor"}
    if cmp:
        row["why"] += "; " + fmt_compare(cmp)
    if ev is not None:
        w = fit_sets([s for s in sets if not s["missed"]])
        live = [s for s in sets if not s["missed"] and s.get("source") != "silent"]
        t = ranker.best_threshold([(s["files"], s["ys"], scored(w, s)) for s in live], 2, MIN_PRECISION)
        row["threshold"] = f"{t:.2f}"
        silent = [s for s in sets if s.get("source") == "silent"]
        if silent:
            # fitted, so an optimistic number: the share of the silence tasks the round's own model would print for
            loud = sum(1 for s in silent if ranker.select(s["files"], scored(w, s), t, 2, limit=1))
            ev["silent"] = {"n": len(silent), "loud": loud / len(silent)}
        if write and promote:
            ranker.save(os.path.join(p4, "models", "ranker.json"), w, t, round_=int(row["round"]), trained=now,
                        per_file=2, floor={"r-precision": round(ev["r-precision"], 4),
                                           "precision": round(ev["precision"], 4),
                                           "short": round(short["rate"], 4)},
                        features=["base"] + (["near"] if __import__("near").ON else []), tasks=len(live))
    row["seconds"] = f"{time.time() - t0:.1f}"
    if write:
        path = os.path.join(p4, "models", "eval.tsv")
        head = EVAL_HEAD if not os.path.exists(path) else ""
        cols = EVAL_HEAD.rstrip("\n").split("\t")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(head + "\t".join(row.get(c, "").replace("\t", " ") for c in cols) + "\n")
    row["eval"] = ev
    row["compare"] = cmp
    return row


# --- raw against edited (5.2 step 3, 5.6) ----------------------------------------------------------------

def has_edited(p4):
    return any(r.get("source") == "store+edited" for r in lb.read_tsv(lb.mpath(p4, lb.TRAIN)))


def raw_vs_edited(p4, idx=None):
    """The Colab method: fit once on the raw labels and once on the edited ones (the teacher's rows in place of
    their tasks' raw labels), and score both on held-out raw labels, the same folds for both. Every teacher row
    counts here, held or not, so a held batch can be judged again. {n, edited_tasks, held_edited, raw, edited,
    raw_on_edited, edited_on_edited, ok, batches}; ok is None when fewer than 3 tasks have raw labels."""
    if idx is None:
        idx, _ = st.ensure_index(p4)
    edited = [lb.as_label(r) for r in lb.read_tsv(lb.mpath(p4, lb.TRAIN)) if r.get("source") == "store+edited"]
    batches = sorted({lb.batch_of(r.get("note", "")) for r in edited} - {""})
    raw = [lb.as_label(r) for r in lb.read_tsv(lb.mpath(p4, lb.RAW))]
    etasks = {r["task"] for r in edited}
    # two label sets compared on the same tasks: the silence tasks (no positive, the same on both sides) stay out
    raw_sets = {s["task"]: s for s in build_sets(p4, idx, rows=lb.recency(p4, raw))
                if not s["missed"] and s.get("source") != "silent"}
    ed_sets = {s["task"]: s for s in build_sets(p4, idx, rows=lb.recency(p4, [r for r in raw if r["task"] not in
                                                                              etasks] + edited))
               if not s["missed"] and s.get("source") != "silent"}
    live = sorted(raw_sets, key=lambda t: (raw_sets[t].get("time", ""), t))
    out = {"n": len(live), "edited_tasks": len(etasks), "held_edited": 0, "raw": None, "edited": None,
           "raw_on_edited": None, "edited_on_edited": None, "ok": None, "batches": batches}
    if len(live) < 3:
        return out
    got = {"raw": {}, "edited": {}}
    for fold in folds([raw_sets[t] for t in live]):
        held = {live[k] for k in fold}
        ws = {"raw": fit_sets([raw_sets[t] for t in live if t not in held]),
              "edited": fit_sets([s for t, s in ed_sets.items() if t not in held])}
        for t in held:
            s = raw_sets[t]
            n = sum(s["ys"])
            for name, w in ws.items():
                m = ranker.metrics(s["ys"], scored(w, s), [])
                got[name][t] = m["r-precision"] * n / max(n, s["n_pos"])
    mean_of = lambda d, ks: sum(d[k] for k in ks) / len(ks) if ks else None  # noqa: E731
    on_edited = [t for t in live if t in etasks]
    out.update(raw=mean_of(got["raw"], live), edited=mean_of(got["edited"], live), held_edited=len(on_edited),
               raw_on_edited=mean_of(got["raw"], on_edited), edited_on_edited=mean_of(got["edited"], on_edited))
    out["ok"] = out["edited"] + 1e-9 >= out["raw"]
    return out


def fmt_compare(c):
    if c is None:
        return "no teacher edits yet"
    if c["ok"] is None:
        return f"raw against edited: fewer than 3 tasks with raw labels ({c['n']}), not compared"
    s = (f"raw against edited on held-out raw labels: raw {c['raw']:.3f}, edited {c['edited']:.3f} r-precision over "
         f"{c['n']} tasks ({c['edited_tasks']} edited")
    if c["held_edited"]:
        s += f"; on the {c['held_edited']} edited tasks raw {c['raw_on_edited']:.3f}, edited {c['edited_on_edited']:.3f}"
    return s + ("): edited at or above raw" if c["ok"] else "): edited BELOW raw; `train` holds its batches")


def hold_batches(p4, batches, why):
    """Mark teacher batches held in models/teacher-batches.json (the owner sets `status` back to ok to release)."""
    cur = lb.read_batches(p4)
    for b in batches:
        e = cur.setdefault(b, {})
        if e.get("status") != "held":
            e["status"] = "held"
            e["why"] = why
    ranker.write_atomic(lb.mpath(p4, lb.BATCHES), json.dumps(cur, indent=1, ensure_ascii=False) + "\n")


# --- the dictionary check (5.3) --------------------------------------------------------------------------

QUOTE_RE = re.compile(r"\"([^\"]{2,400})\"")


def first_quote(because):
    for b in because:
        m = QUOTE_RE.search(b or "")
        if m:
            return m.group(1)
    return ""


def top5(p4, idx, text, vocab_override=None):
    """The ids of the top 5 candidates the query would rank for `text` (threshold aside), with the vocabulary
    `vocab_override` in place of the index's."""
    import p4 as cli
    saved = idx.get("vocab")
    if vocab_override is not None:
        idx["vocab"] = vocab_override
    try:
        r = cli.rank(p4, text, idx=idx, k=5)
    finally:
        idx["vocab"] = saved
    return r


def working_messages(p4, idx, limit=200):
    """The held-out set of messages that already worked: served lines that were used with no follow-up (from
    labels.tsv's usage rows); failing those, the newest completed rows longer than a short turn."""
    msgs = lb.working_texts(p4, limit)
    if msgs:
        return msgs
    out = []
    files = st.load_store(p4)
    rows = [e for k, v in files.items() if k.startswith(st.MESSAGES + "/") for e in v if st.completed(e)]
    rows.sort(key=lambda e: e.time, reverse=True)
    for e in rows:
        fp = st.unquote(e.fields.get("fingerprint", e.value))
        if len(st.norm_token(fp).split()) > st.SHORT_WORDS and not fp.lstrip().startswith("<"):
            out.append(fp)
        if len(out) >= limit:
            break
    return out


def is_owner_entry(v):
    return "owner" in (v.get("source") or "").lower()


def dictionary_check(p4, idx=None, write=True, harm_max=0.05):
    """Each `on` entry with a meaning: (1) a query on the misread message ranks a `points-at:` entry in the top 5
    with the entry on; (2) over the working messages the top 5 is unchanged for >= 95% with it on. A failing entry
    is set `status: off` in vocabulary.md, unless the owner wrote it (listed, left as it is)."""
    if idx is None:
        idx, _ = st.ensure_index(p4)
    vocab = list(idx.get("vocab", []))
    working = working_messages(p4, idx)
    results = []
    counts = {"on": 0, "off": 0, "fixed": 0, "harmed": 0}
    to_off = []
    base_cache = {}
    for v in vocab:
        if v.get("pending") or v.get("status", "on") != "on":
            counts["off" if v.get("status") == "off" else "on"] += 0 if v.get("pending") else 1
            continue
        msg = first_quote(v.get("because", []))
        fixed = False
        if msg:
            got = top5(p4, idx, msg, vocab_override=[v])
            fixed = bool(set(got) & set(v.get("points-at", [])))
        changed = total = 0
        for m in working:
            tok = st.norm_token(m)
            if v.get("norm") and v["norm"] not in tok and not all(t in set(ranker.tokens(m))
                                                                   for t in v.get("term_toks") or ["\0"]):
                total += 1       # the entry cannot touch a message without its term: unchanged by construction
                continue
            total += 1
            if m not in base_cache:
                base_cache[m] = top5(p4, idx, m, vocab_override=[])
            on = top5(p4, idx, m, vocab_override=[v])
            changed += on != base_cache[m]
        harmed = total > 0 and changed / total > harm_max
        status_after = "on"
        if not fixed or harmed:
            if is_owner_entry(v):
                status_after = "on"
            else:
                status_after = "off"
                to_off.append(v)
        counts["fixed"] += fixed
        counts["harmed"] += harmed
        counts["on" if status_after == "on" else "off"] += 1
        results.append({"term": v["term"], "line": v.get("line"), "fixed": fixed, "harmed": harmed,
                        "changed": changed, "working": total, "status_after": status_after,
                        "owner": is_owner_entry(v), "message": msg[:120]})
    if write and to_off:
        set_status_off(p4, [v["line"] for v in to_off])
    return {"entries": results, "counts": counts, "working": len(working)}


def set_status_off(p4, lines):
    """Turn the entries opening at these lines `status: off`, editing only their status line: every other byte of
    vocabulary.md (the owner's edits) stays as it was."""
    path = os.path.join(st.store_dir(p4), st.VOCABULARY)
    text = st.read_text(path)
    ls = text.split("\n")
    starts = sorted(set(lines))
    for s in starts:
        i = s - 1
        j = i + 1
        done = False
        while j < len(ls) and (ls[j].startswith("  ") or ls[j].startswith(st.CONT_PREFIX)):
            if re.match(r"^  status:", ls[j]):
                ls[j] = "  status: off"
                done = True
            j += 1
        if not done:
            ls.insert(j, "  status: off")
            starts = [x + 1 if x > s else x for x in starts]
    ranker.write_atomic(path, "\n".join(ls))


# --- the command line ------------------------------------------------------------------------------------

def fmt(ev):
    if not ev:
        return "no held-out numbers (fewer than 3 labelled tasks)"
    s = (f"r-precision {ev['r-precision']:.3f} (word overlap {ev['baseline']:.3f}), recall@20 {ev['recall@20']:.3f}, "
         f"precision at threshold {ev['precision']:.3f}, over {ev['n']} tasks" +
         (f" ({ev['missed']} with no labelled entry drawn)" if ev["missed"] else ""))
    for k in ("pool", "history", "repo"):
        if k in ev:
            s += f"; {k} subset r-precision {ev[k]['r-precision']:.3f}, top-5 hit {ev[k]['top5']:.2f} (n {ev[k]['n']})"
    if ev.get("silent"):
        s += f"; {ev['silent']['n']} silence tasks" + (f", {ev['silent']['loud']:.0%} printed for (fitted)"
                                                       if "loud" in ev["silent"] else "")
    return s


def cmd_train(args):
    p4 = args.p4
    if getattr(args, "if_owed", False):
        ok, why = owed(p4)
        if not ok:
            print(f"train: not owed ({why})")
            return 0
    row = run_round(p4, write=True, now=args.now or None,
                    sources=set(args.sources.split(",")) if args.sources else None)
    print(f"train: round {row['round']} {row['promoted']} ({row['why']}); {fmt(row['eval'])}; "
          f"short {row['short']}; dictionary {row['dictionary']}; {row['seconds']} s")
    return 0


def cmd_eval(args):
    row = run_round(args.p4, write=False, now=args.now or None,
                    sources=set(args.sources.split(",")) if args.sources else None, dictionary=not args.no_dictionary)
    print(f"eval: {fmt(row['eval'])}; short {row['short']}; would be {row['promoted']} ({row['why']})")
    if row.get("compare"):
        print(f"eval: {fmt_compare(row['compare'])}")
    if args.json:
        ev = dict(row["eval"] or {})
        ev.pop("rows", None)
        out = {"eval": ev, "short": row["short"], "promoted": row["promoted"]}
        if row.get("compare"):
            out["compare"] = row["compare"]
        print(json.dumps(out))
    return 0


def cmd_dictionary(args):
    res = dictionary_check(args.p4, write=not args.dry)
    for r in res["entries"]:
        flag = "ok" if r["fixed"] and not r["harmed"] else ("kept (owner's)" if r["owner"] else "set off")
        print(f"  {r['term']}: fixes its message {'yes' if r['fixed'] else 'no'}, changes {r['changed']} of "
              f"{r['working']} working messages -> {flag}")
    c = res["counts"]
    print(f"dictionary check: {c['on']} on, {c['off']} off, {c['fixed']} fixed, {c['harmed']} harmed, "
          f"over {res['working']} working messages")
    return 0
