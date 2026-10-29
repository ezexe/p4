#!/usr/bin/env python3
"""pick_model.py — the pool's model road: a ranker trained on the store's own pools picks what bears on a task.

The children road spends one pick-reader agent per store file on every session's first prompt. Every pool it
wrote is a labelled example: the task, the barrier's rows, and the rows its steering section picked. This script
learns from those examples and picks for a new task in the children's own picks shape, so `phi.py pool --picks`
folds the model's picks exactly as it folds a child's. It never reads past the barrier: a pick is a LIVE row's
`<file>:<line>`, its text stays the hot file's, and every SPENT, FREED and EXPIRED row is out of its reach.

Deterministic, standard library only, no network, no agent. The model is a logistic ranker over term-overlap,
file, kind and age features (and, with --tokens, the row's own words), stored as JSON; it is never a source of
anything the store holds.

Subcommands:
  pairs   the labelled pairs: for every session's recall-pool.md, its task, the barrier rows timed no later than
          its pooled: line (tombstones aside), and which its steering section picked — matched on file, time and
          head, since a picks file's virtual line numbers move as sessions are added. --jsonl writes them.
  eval    leave-one-pool-out: each pool scored by a model trained on the others, against term overlap alone —
          R-precision (the pool's n picks against the model's top n), recall in the top 20, and the precision and
          recall of the picks the threshold makes.
  train   fit on every pool, choose the pick threshold, write the model (default <p4>/models/pick-model.json);
          when a model was there, also write the round's change in the phi_prune.delta format
          (pick-model.rNN.phid: the changed weights' positions as Fibonacci gap codes, values as a sign and a
          Fibonacci-coded level), which phi_prune.delta.decode_delta reads. The JSON is the model; the delta is
          the round's record, quantized.
  picks   the picks file for one task: `picks (model) — <file>, <n> of <total> …` heads and one
          `<file>:<line> || bears: model <score>; shares: <terms>` line per pick, at most six a file, strongest
          first, over the LIVE rows of the barrier. Exit 3 when no model exists — take the skeleton road.
  shadow  the children's picks against the model's for one pool, one row in <p4>/models/shadow.tsv and one line
          printed; the pool folds the children's picks alone.
"""

import argparse
import datetime
import json
import math
import os
import random
import re
import sys
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import partition as pt  # noqa: E402
import phi  # noqa: E402 — the barrier: rows, states, distilled heads

DIM = 1 << 18                 # hashed feature space
PER_FILE = 6                  # a child's cap, kept
TOP_EVAL = 20
EPOCHS, LR, L2 = 25, 0.1, 1e-4
REVIEW_ALTS = 4               # runners-up per file on the operator's review sheet
REVIEW_HEAD_CHARS = 140       # a review line's head: the barrier's own width
RANKER_TIMEOUT_S = 10          # a ranker server that has not answered by then is down: the JSON ranker picks
DEFAULT_AUDIT = 5             # `pool-audit:` unnamed — one session in five runs the children beside the model
EFFORTS = ("low", "medium", "high")   # `pool-effort:` — low: the JSON ranker alone; medium: one node of the store's
                                      # tree; high: the tree's ensemble; unnamed: the single .pt ranker, as before
DELTA_DIGITS = 12             # Fibonacci digits for a round's delta: 376 levels a side
POOL_STEER_RE = re.compile(r"^- \[([a-z-]+\.md) (\d{4}-\d\d-\d\d \d\d:\d\d|\(no time\))[^\]]*\] (.*?); bears: (.*)$")
MODEL_CREDIT_RE = re.compile(r"\(\d+, [a-z+]*\bmodel\b")   # `read: <file> (<n>, model)` — a file the model picked
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)+")
STOP = frozenset("""the and for that this with from are was were not but its his her their them they you your our
into onto than then when what which who whom how why where there here have has had been being its it's out off
any all each every one two own same such only also just very more most less least over under again once both
some none nor too can will would should could may might must shall per via about after before between while
during without within upon across whose those these ever never always still yet already itself""".split())


# ─── text ───────────────────────────────────────────────────────────────────────────────────────────────

def tokens(text):
    """Lower-cased words of three letters or more (and dotted numbers like 3.15), stop words out; a camelCase or
    snake_case name also yields its parts, so kServiceLeadMs meets 'service lead'."""
    out = []
    for t in TOKEN_RE.findall(text or ""):
        parts = [t] + [p for p in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", t) if p != t] if not t[0].isdigit() else [t]
        for p in parts:
            p = p.lower()
            if (len(p) >= 3 or "." in p) and p not in STOP:
                out.append(p)
    return out


def row_text(r):
    return " ".join([r["value"]] + [v for k, v in r["fields"].items() if k not in ("time", "status")])


def idf_table(docs):
    n = len(docs)
    df = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    return {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}, n


def bm25(task_terms, doc, idf, avgdl, k1=1.2, b=0.75):
    tf = {}
    for t in doc:
        tf[t] = tf.get(t, 0) + 1
    s = 0.0
    for t in task_terms:
        if t in tf:
            f = tf[t]
            s += idf.get(t, 0.0) * f * (k1 + 1) / (f + k1 * (1 - b + b * len(doc) / avgdl))
    return s


# ─── features ───────────────────────────────────────────────────────────────────────────────────────────

def h(name):
    return zlib.crc32(name.encode("utf-8")) % DIM


def days_between(earlier, later):
    try:
        a = datetime.datetime.strptime(earlier[:16], "%Y-%m-%d %H:%M")
        b = datetime.datetime.strptime(later[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        try:
            a = datetime.datetime.strptime(earlier[:10], "%Y-%m-%d")
            b = datetime.datetime.strptime(later[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return max(0.0, (b - a).total_seconds() / 86400)


def candidate_features(task, rows, docs, idf, avgdl, now, with_tokens):
    """One sparse feature dict {index: value} per candidate row, and the shared terms for each."""
    terms = list(dict.fromkeys(tokens(task)))
    scores = [bm25(terms, d, idf, avgdl) for d in docs]
    top = max(scores) or 1.0
    order = sorted(range(len(rows)), key=lambda i: -scores[i])
    rank = {i: k for k, i in enumerate(order)}
    # a child reads the barrier's head alone, and picks at most six a file: the head's own overlap, ranked in its file
    heads = [tokens(phi.distilled(r, phi.BARRIER_HEAD_CHARS)) for r in rows]
    head_scores = [bm25(terms, d, idf, avgdl) for d in heads]
    head_top = max(head_scores) or 1.0
    file_rank, seen = {}, {}
    for i in sorted(range(len(rows)), key=lambda i: -(scores[i] + head_scores[i])):
        f = rows[i]["file"]
        file_rank[i] = seen.get(f, 0)
        seen[f] = file_rank[i] + 1
    tset = set(terms)
    out, shared_terms = [], []
    for i, (r, d) in enumerate(zip(rows, docs)):
        shared = [t for t in dict.fromkeys(d) if t in tset]
        rare = [t for t in shared if idf.get(t, 0) > 3.0]
        age = days_between(r["time"], now) if r["time"] else None
        x = {
            h("bias"): 1.0,
            h("bm25"): scores[i] / top,
            h("bm25-rank"): 1.0 / (1 + rank[i]),
            h("head-bm25"): head_scores[i] / head_top,
            h("file-rank"): 1.0 / (1 + file_rank[i]),
            h("file-top6"): 1.0 if file_rank[i] < PER_FILE else 0.0,
            h("top10"): 1.0 if rank[i] < 10 else 0.0,
            h("overlap"): len(shared) / max(1, len(tset)),
            h("rare"): min(len(rare), 5) / 5,
            h("length"): math.log1p(len(d)) / 5,
            h("file=" + r["file"]): 1.0,
            h("kind=" + r["kind"]): 1.0,
            h("state=" + r["state"]): 1.0,
        }
        if age is None:
            x[h("no-time")] = 1.0
        else:
            x[h("age")] = math.log1p(age) / 4
            x[h("recent")] = 1.0 if age <= 2 else 0.0
        if with_tokens:
            for t in set(d):
                x[h("tok=" + t)] = x.get(h("tok=" + t), 0.0) + 0.2
            for t in shared:
                x[h("shared=" + t)] = 0.5
        out.append(x)
        shared_terms.append(sorted(shared, key=lambda t: -idf.get(t, 0))[:4])
    return out, scores, shared_terms


def sigmoid(z):
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def score(w, x):
    return sigmoid(sum(w.get(k, 0.0) * v for k, v in x.items()))


def fit(examples, epochs=EPOCHS, lr=LR, l2=L2, seed=0):
    """Logistic regression by AdaGrad SGD over (x, y) pairs; positives weighed up to balance the classes."""
    pos = sum(y for _, y in examples) or 1
    neg = len(examples) - pos or 1
    wpos = math.sqrt(neg / pos)
    w, g2 = {}, {}
    rng = random.Random(seed)
    order = list(range(len(examples)))
    for _ in range(epochs):
        rng.shuffle(order)
        for i in order:
            x, y = examples[i]
            p = score(w, x)
            grad = (p - y) * (wpos if y else 1.0)
            for k, v in x.items():
                g = grad * v + l2 * w.get(k, 0.0)
                g2[k] = g2.get(k, 0.0) + g * g
                w[k] = w.get(k, 0.0) - lr * g / math.sqrt(g2[k] + 1e-8)
    return w


# ─── the pools as pairs ─────────────────────────────────────────────────────────────────────────────────

def all_pools(store):
    p4 = pt.p4_of(store)
    stores = pt.session_stores(store) if p4 else [store]
    out = []
    for s in stores:
        path = os.path.join(s, "recall-pool.md")
        if os.path.exists(path):
            out.append(path)
    return out


def parse_pool(path):
    text = phi.read(path)
    task = re.search(r"^task:\s*(.*)$", text, re.M)
    pooled = re.search(r"^pooled:\s*(\d{4}-\d\d-\d\d \d\d:\d\d)", text, re.M)
    session = re.search(r"^session:\s*(\S+)", text, re.M)
    read = re.search(r"^read:\s*(.*)$", text, re.M)
    steer = text.split("## steering", 1)[1].split("\n## ", 1)[0] if "## steering" in text else ""
    picks = []
    for l in steer.splitlines():
        m = POOL_STEER_RE.match(l)
        if m:
            picks.append((m.group(1), m.group(2), m.group(3).rstrip("…").strip()))
    # a pool whose read: line credits the model was steered by the model's own picks: never a label for it
    by_model = bool(read and MODEL_CREDIT_RE.search(read.group(1)))
    sid = session.group(1)[:8] if session else ""
    # the id the models record a pool by, never empty: a pool with no session: line takes its store's directory name
    pid = sid or os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(path))))
    return {"path": path, "task": task.group(1).strip() if task else "", "pooled": pooled.group(1) if pooled else "",
            "session": sid, "id": pid, "picks": picks, "by_model": by_model}


def labelled_pool(p):
    """A pool the ranker may learn from: a task, a time, steering picks, and no pick of its own making."""
    return bool(p["task"] and p["pooled"] and p["picks"] and not p["by_model"])


def labels_dir(store):
    p4 = pt.p4_of(store)
    return os.path.join(p4 or os.path.dirname(os.path.abspath(store)), "models", "labels")


def parse_label_file(path):
    """An audit's labels, written by `label`: the children's picks for a task, by file, time and head."""
    task = pooled = session = ""
    reader = "children"
    picks = []
    with open(path, encoding="utf-8") as f:
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


def label_pools(store):
    """Every pool the ranker may learn from: each session's recall pool a child or the operator's pass picked (never
    one the model picked alone), and each audit's children labels in models/labels/."""
    out = [p for p in (parse_pool(x) for x in all_pools(store)) if labelled_pool(p)]
    d = labels_dir(store)
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name.endswith(".tsv"):
                p = parse_label_file(os.path.join(d, name))
                if labelled_pool(p):
                    out.append(p)
    return out


def corpus(store):
    rows = phi.barrier_rows(store, "")[0]
    rows = [r for r in rows if r["file"] != "tombstones.md"]
    docs = [tokens(row_text(r)) for r in rows]
    idf, _ = idf_table(docs)
    avgdl = sum(len(d) for d in docs) / max(1, len(docs))
    return rows, docs, idf, avgdl


def build_pairs(store):
    """[{task, pooled, session, rows: [row index], labels: [0/1], matched, steering}] — one per pool with picks."""
    rows, docs, idf, avgdl = corpus(store)
    pools = []
    for p in label_pools(store):
        cand = [i for i, r in enumerate(rows) if not r["time"] or r["time"][:16] <= p["pooled"]]
        labels, matched = [0] * len(cand), 0
        for f, tm, head in p["picks"]:
            for j, i in enumerate(cand):
                r = rows[i]
                if r["file"] == f and (r["time"] or "(no time)") == tm and \
                        phi.distilled(r, 400).startswith(head[:40]):
                    labels[j] = 1
                    matched += 1
                    break
        if matched:
            pools.append({**p, "rows": cand, "labels": labels, "matched": matched, "steering": len(p["picks"])})
    return pools, (rows, docs, idf, avgdl)


def pool_examples(pool, data, with_tokens):
    rows, docs, idf, avgdl = data
    sub = [rows[i] for i in pool["rows"]]
    xs, bm, shared = candidate_features(pool["task"], sub, [docs[i] for i in pool["rows"]], idf, avgdl,
                                        pool["pooled"], with_tokens)
    return xs, bm, shared


# ─── the .pt ranker's score as a feature ────────────────────────────────────────────────────────────────

OOF_FILE = "ranker-oof.json"    # phi_rank's out-of-fold scores of every labelled pool, by pool id and text key
TREE_OOF_FILE = "tree-oof.json"  # phi_rank.tree's: the same, per effort (medium, high), from fold trees


def text_key(text):
    """A candidate's key in the out-of-fold scores — phi_rank.text_key, the same sha1 of the same distilled text."""
    import hashlib
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def load_oof(store, effort=""):
    """{pool id: {text key: score}} for the .pt source `effort` names: the tree's scores at medium or high from
    models/tree-oof.json, the single ranker's from models/ranker-oof.json otherwise; {} when there is none or it is
    unreadable."""
    try:
        if effort in ("medium", "high"):
            with open(os.path.join(models_root(store), TREE_OOF_FILE), encoding="utf-8") as f:
                pools = json.load(f).get("efforts", {}).get(effort, {})
        else:
            with open(os.path.join(models_root(store), OOF_FILE), encoding="utf-8") as f:
                pools = json.load(f).get("pools", {})
        return pools if isinstance(pools, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def pt_source(effort):
    """The name of the .pt source an effort asks for, as the model records it."""
    return f"tree:{effort}" if effort in ("medium", "high") else "ranker"


def add_pt(xs, scores):
    """The .pt ranker's scores as one feature, z-scored within the pool: its mean contributes nothing, so a pool
    scored without it (no server, no out-of-fold score) keeps the JSON ranker's own scale and threshold."""
    if not scores or len(scores) != len(xs):
        return xs
    mu = sum(scores) / len(scores)
    sd = math.sqrt(sum((x - mu) ** 2 for x in scores) / len(scores)) or 1.0
    for x, v in zip(xs, scores):
        x[h("pt-z")] = max(-3.0, min(3.0, (v - mu) / sd)) / 3
    return xs


def pool_pt(pool, data, oof):
    """A pool's out-of-fold .pt scores in its candidates' order, or None when phi_rank has not scored this pool."""
    got = oof.get(pool["id"])
    if not got:
        return None
    sc = [got.get(text_key(phi.distilled(data[0][i], 400))) for i in pool["rows"]]
    return None if any(v is None for v in sc) else sc


def loo_rprecision(pools, feats, data):
    """Mean leave-one-pool-out r-precision of the JSON ranker on these features."""
    got = []
    for k, p in enumerate(pools):
        w = fit([(x, y) for j, q in enumerate(pools) if j != k for x, y in zip(feats[j][0], q["labels"])])
        got.append(metrics(p["labels"], [score(w, x) for x in feats[k][0]], [])["r-precision"])
    return sum(got) / len(got) if got else 0.0


# ─── selection and metrics ──────────────────────────────────────────────────────────────────────────────

def select(rows, scores, threshold, per_file=PER_FILE):
    """Indices picked: score at or above the threshold, at most per_file a file, strongest first."""
    by_file = {}
    for i in sorted(range(len(rows)), key=lambda i: -scores[i]):
        if scores[i] < threshold:
            break
        lst = by_file.setdefault(rows[i]["file"], [])
        if len(lst) < per_file:
            lst.append(i)
    return [i for lst in by_file.values() for i in lst]


def metrics(labels, scores, picked):
    n = sum(labels)
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    rprec = sum(labels[i] for i in order[:n]) / n if n else 0.0
    rec20 = sum(labels[i] for i in order[:TOP_EVAL]) / n if n else 0.0
    hit = sum(labels[i] for i in picked)
    prec = hit / len(picked) if picked else 0.0
    rec = hit / n if n else 0.0
    return {"r-precision": rprec, "recall@20": rec20, "precision": prec, "recall": rec,
            "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0, "picked": len(picked), "labelled": n}


def best_threshold(scored):
    """The threshold, from 0.30 to 0.95, with the best mean F1 over [(rows, labels, scores)]."""
    best, best_f1 = 0.5, -1.0
    for k in range(30, 96, 5):
        t = k / 100
        f1 = sum(metrics(lab, sc, select(rw, sc, t))["f1"] for rw, lab, sc in scored) / max(1, len(scored))
        if f1 > best_f1:
            best, best_f1 = t, f1
    return best


def mean(dicts, key):
    return sum(d[key] for d in dicts) / max(1, len(dicts))


# ─── model file ─────────────────────────────────────────────────────────────────────────────────────────

def model_path(store, given):
    if given:
        return given
    p4 = pt.p4_of(store)
    return os.path.join(p4 or os.path.dirname(os.path.abspath(store)), "models", "pick-model.json")


def load_model(path):
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    m["w"] = {int(k): v for k, v in m["w"].items()}
    return m


def write_atomic(path, text):
    """Write text to path whole or not at all: a temp file beside it, flushed, then os.replace — so a hook reading
    the model while a background retrain writes it sees the old file or the new one, never half of either.
    On Windows os.replace is refused (PermissionError) while any reader holds the target open, so the replace is
    retried with a short backoff; a refusal that outlasts it leaves no temp file behind and raises."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    for attempt in range(50):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 49:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            time.sleep(min(0.002 * (attempt + 1), 0.05))


def save_model(path, m):
    out = {**m, "w": {str(k): round(v, 6) for k, v in sorted(m["w"].items()) if abs(v) > 1e-9}}
    write_atomic(path, json.dumps(out, indent=1) + "\n")


# ─── a round's delta, in phi_prune.delta's format ───────────────────────────────────────────────────────

def _fibs(n):
    f = [1, 2]
    while len(f) < n:
        f.append(f[-1] + f[-2])
    return f[:n]


def fib_code(n):
    """n >= 1: Zeckendorf digits least significant first, then a closing 1 — phi_prune.gaps.fib_code."""
    places = [1, 2]
    while places[-1] <= n:
        places.append(places[-1] + places[-2])
    digits = [0] * len(places)
    for k in range(len(places) - 1, -1, -1):
        if places[k] <= n:
            digits[k] = 1
            n -= places[k]
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
    return "".join(map(str, digits)) + "1"


def levels_for(n_digits):
    """FibonacciEncoder(n_digits).max_value: the largest sum of non-adjacent digits."""
    f = _fibs(n_digits)
    best = [0, f[0]]
    for i in range(1, n_digits):
        best.append(max(best[-1], best[-2] + f[i]))
    return best[-1]


def encode_round(old_w, new_w, n_digits=DELTA_DIGITS):
    """(header, payload) of new_w - old_w over the changed positions, as phi_prune.delta.encode_delta writes them
    for one tensor `w` of shape [DIM] with keep the changed fraction."""
    changed = sorted(k for k in set(old_w) | set(new_w) if abs(new_w.get(k, 0.0) - old_w.get(k, 0.0)) > 1e-9)
    levels = levels_for(n_digits)
    vals = [new_w.get(k, 0.0) - old_w.get(k, 0.0) for k in changed]
    scale = (max(abs(v) for v in vals) / levels) if vals else 1.0
    prev, parts = -1, []
    for k in changed:
        parts.append(fib_code(k - prev))
        prev = k
    for v in vals:
        parts.append(("1" if v < 0 else "0") + fib_code(int(round(abs(v) / scale)) + 1))
    header = {"keep": len(changed) / DIM, "n_digits": n_digits, "levels": levels,
              "tensors": [{"name": "w", "shape": [DIM], "n_kept": len(changed), "scale": scale}], "skipped": [],
              "source": "vlds scripts/pick_model.py"}
    return header, "".join(parts)


# ─── subcommands ────────────────────────────────────────────────────────────────────────────────────────

def cmd_pairs(args, store):
    pools, data = build_pairs(store)
    rows = data[0]
    print(f"pairs — {len(pools)} pools with picks, {len(rows)} barrier rows (tombstones aside); "
          f"{sum(p['matched'] for p in pools)} of {sum(p['steering'] for p in pools)} steering lines matched")
    for p in pools:
        print(f"  {p['session'] or '?':<8} {p['pooled']}  {p['matched']:>2}/{p['steering']:<2} picks, "
              f"{len(p['rows'])} candidates — {phi.clip(p['task'], 90)}")
    if args.jsonl:
        with open(args.jsonl, "w", encoding="utf-8", newline="\n") as f:
            for p in pools:
                for i, y in zip(p["rows"], p["labels"]):
                    r = rows[i]
                    f.write(json.dumps({"pool": p["session"], "pool_id": p["id"], "pooled": p["pooled"], "task": p["task"],
                                        "file": r["file"], "time": r["time"], "kind": r["kind"],
                                        "state": r["state"], "text": phi.distilled(r, 400), "label": y},
                                       ensure_ascii=False) + "\n")
        print(f"→ {args.jsonl}")
    return 0


def cmd_eval(args, store):
    pools, data = build_pairs(store)
    if len(pools) < 3:
        print(f"eval — {len(pools)} labelled pools; at least 3 are needed")
        return 1
    feats = [pool_examples(p, data, args.tokens) for p in pools]
    model_m, base_m = [], []
    for k, p in enumerate(pools):
        train = [(x, y) for j, q in enumerate(pools) if j != k for x, y in zip(feats[j][0], q["labels"])]
        w = fit(train)
        scored_train = [([data[0][i] for i in q["rows"]], q["labels"], [score(w, x) for x in feats[j][0]])
                        for j, q in enumerate(pools) if j != k]
        t = best_threshold(scored_train)
        rows = [data[0][i] for i in p["rows"]]
        sc = [score(w, x) for x in feats[k][0]]
        model_m.append(metrics(p["labels"], sc, select(rows, sc, t)))
        bm = feats[k][1]
        n = sum(p["labels"])
        top = sorted(range(len(bm)), key=lambda i: -bm[i])[:n]
        base_m.append(metrics(p["labels"], bm, top))
        if args.verbose:
            m = model_m[-1]
            print(f"  {p['session']:<8} n={n:<3} model r-prec {m['r-precision']:.2f} rec@20 {m['recall@20']:.2f} "
                  f"picked {m['picked']:<3} P {m['precision']:.2f} R {m['recall']:.2f} | overlap r-prec "
                  f"{base_m[-1]['r-precision']:.2f} rec@20 {base_m[-1]['recall@20']:.2f}")
    print(f"eval — leave-one-pool-out over {len(pools)} pools ({'with' if args.tokens else 'without'} token features)")
    print(f"  model         r-precision {mean(model_m, 'r-precision'):.3f}  recall@20 {mean(model_m, 'recall@20'):.3f}  "
          f"picks: precision {mean(model_m, 'precision'):.3f} recall {mean(model_m, 'recall'):.3f} "
          f"f1 {mean(model_m, 'f1'):.3f} ({mean(model_m, 'picked'):.1f} a pool against {mean(model_m, 'labelled'):.1f})")
    print(f"  term overlap  r-precision {mean(base_m, 'r-precision'):.3f}  recall@20 {mean(base_m, 'recall@20'):.3f}")
    effort = pool_effort(store)
    oof = load_oof(store, effort)
    pt_scores = [pool_pt(p, data, oof) for p in pools] if oof else []
    if sum(1 for x in pt_scores if x) >= 3:
        with_pt = [(add_pt([dict(x) for x in f[0]], sc), f[1], f[2]) for f, sc in zip(feats, pt_scores)]
        print(f"  with the .pt feature ({pt_source(effort)}, out-of-fold, {sum(1 for x in pt_scores if x)} pools "
              f"scored): r-precision "
              f"{loo_rprecision(pools, with_pt, data):.3f}")
    return 0


def cmd_train(args, store):
    pools, data = build_pairs(store)
    if not pools:
        print("train — no labelled pool in the store; nothing written")
        return 1
    feats = [pool_examples(p, data, args.tokens) for p in pools]
    # the .pt ranker's out-of-fold score joins the features only when it raises the held-out r-precision: the JSON
    # ranker can only gain from it, and a .pt model that ranks worse than word overlap simply carries no weight.
    # The source is the one the index's pool-effort names: the tree at medium or high, the single ranker otherwise
    effort = pool_effort(store)
    effort = effort if effort in ("medium", "high") else ""
    oof, use_pt, held = load_oof(store, effort), False, None
    pt_scores = [pool_pt(p, data, oof) for p in pools] if oof else []
    if sum(1 for x in pt_scores if x) >= 4 and len(pools) >= 4:
        plain = loo_rprecision(pools, feats, data)
        with_pt = [(add_pt([dict(x) for x in f[0]], sc), f[1], f[2]) for f, sc in zip(feats, pt_scores)]
        boosted = loo_rprecision(pools, with_pt, data)
        use_pt, held = boosted > plain, {"without_pt": round(plain, 4), "with_pt": round(boosted, 4),
                                         "pt_from": pt_source(effort)}
        if use_pt:
            feats = with_pt
    w = fit([(x, y) for f, p in zip(feats, pools) for x, y in zip(f[0], p["labels"])])
    t = best_threshold([([data[0][i] for i in p["rows"]], p["labels"], [score(w, x) for x in f[0]])
                        for f, p in zip(feats, pools)])
    path = model_path(store, args.model)
    try:
        old = load_model(path) if os.path.exists(path) else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        # a corrupt or conflicted model is what a retrain repairs: start again from round 0, no delta
        print(f"train — the model in place is unreadable ({type(e).__name__}); training a fresh one")
        old = None
    rnd = (old.get("round", 0) + 1) if old else 0
    seen = sorted({p["id"] for p in label_pools(store)})
    save_model(path, {"kind": "vlds pick ranker", "round": rnd, "trained": args.now, "dim": DIM,
                      "tokens": bool(args.tokens), "threshold": t, "per_file": PER_FILE,
                      "pools": [p["session"] for p in pools], "seen": seen, "pt": use_pt,
                      **({"pt_effort": effort} if use_pt and effort else {}),
                      **({"heldout": held} if held else {}), "w": w})
    line = f"train — round {rnd}: {len(pools)} pools, {sum(p['matched'] for p in pools)} picks, threshold {t:.2f} → {path}"
    if held:
        line += (f"; .pt feature from {held['pt_from']} {'kept' if use_pt else 'left out'} (leave-one-out r-precision "
                 f"{held['with_pt']:.3f} with it, {held['without_pt']:.3f} without)")
    if old:
        header, payload = encode_round(old["w"], w)
        dpath = os.path.join(os.path.dirname(path), f"pick-model.r{rnd:02d}.phid")
        write_atomic(dpath, json.dumps(header) + "\n" + payload)
        n = header["tensors"][0]["n_kept"]
        line += f"; delta {n} weights, {len(payload) / max(1, n):.1f} bits each → {dpath}"
    print(line)
    return 0


# ─── the .pt ranker: phi_serve on localhost, this script's client ──────────────────────────────

def models_root(store):
    p4 = pt.p4_of(store)
    return os.path.join(p4 or os.path.dirname(os.path.abspath(store)), "models")


def store_root(store):
    return os.path.dirname(models_root(store))


def same_path(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except (OSError, TypeError, ValueError):
        return False


def neutral_cwd():
    """The working directory for every ranker process: never the store, whose files `python -m` would put first on
    sys.path (a phi_prune/ committed into a shared store must not replace the installed package)."""
    return tempfile.gettempdir()


NOTICES = "retrain-needed.tsv"
RESOLVED = "retrain-resolved.tsv"
NOTICE_QUIET_S = 6 * 3600       # one notice per component and error kind in this long: a failing model is not a flood
NOTICES_HEAD = ("# p4 model retrain notices — time\tepoch\tsession\tcomponent\tkind\terror — written by the vlds "
                "plugin when a model failed unexpectedly and the session fell back (the JSON ranker, the children, the "
                "operator) and carried on; nothing in the session fixes it: the p4-model skill in the model repository "
                "(ezexe/phi) retrains and clears them, by appending to retrain-resolved.tsv — this file is only ever "
                "appended to\n")


def notice_family(component):
    """The model a notice is about: ranker (the .pt ranker and its server), dispatch, or json (the pool ranker)."""
    return "ranker" if "ranker" in component else "dispatch" if "dispatch" in component else "json"


def notify_retrain(store, component, err, session=""):
    """Record that a model failed unexpectedly and needs retraining — the one thing a session does about it. Never
    raises; quiet for NOTICE_QUIET_S per component and error kind. True when a row was written."""
    try:
        path = os.path.join(models_root(store), NOTICES)
        kind = type(err).__name__ if isinstance(err, BaseException) else str(err).split(":", 1)[0].strip()
        text = f"{type(err).__name__}: {err}" if isinstance(err, BaseException) else str(err)
        text = " ".join(text.replace("\t", " ").split())[:300]
        now = time.time()
        if any(r["component"] == component and r["kind"] == kind and now - r["epoch"] < NOTICE_QUIET_S
               for r in open_notices(store)):
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if new:
                f.write(NOTICES_HEAD)
            f.write(f"{time.strftime('%Y-%m-%d %H:%M')}\t{now:.6f}\t{session[:8]}\t{component}\t{kind}\t{text}\n")
        return True
    except Exception:  # noqa: BLE001 — a notice that cannot be written changes nothing about the fallback
        return False


def _rows(path, width):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for l in f:
                parts = l.rstrip("\n").split("\t")
                if not l.startswith("#") and len(parts) >= width:
                    out.append(parts)
    except OSError:
        pass
    return out


def notice_key(epoch, component, kind):
    return f"{float(epoch or 0):.6f}|{component}|{kind}"


def open_notices(store):
    """[{time, epoch, session, component, kind, error}] — the retrain notices no row of retrain-resolved.tsv answers.
    Both files are append-only, so a hook writing a notice and the p4-model skill resolving one never lose a row."""
    mdir = models_root(store)
    resolved = {notice_key(r[1], r[3], r[4]) for r in _rows(os.path.join(mdir, RESOLVED), 6)}
    out = []
    for p in _rows(os.path.join(mdir, NOTICES), 6):
        try:
            epoch = float(p[1] or 0)
        except ValueError:
            continue
        if notice_key(epoch, p[3], p[4]) in resolved:
            continue
        out.append({"time": p[0], "epoch": epoch, "session": p[2], "component": p[3], "kind": p[4],
                    "error": "\t".join(p[5:])})
    return out


def notice_open(store, family):
    return any(notice_family(n["component"]) == family for n in open_notices(store))


class ServerDown(Exception):
    """No ranker server of this store answered: an ordinary fallback, never a notice."""


def ranker_request(store, path, body=None, timeout=RANKER_TIMEOUT_S):
    """(status, reply) from this store's ranker server. Raises ServerDown for anything that is not an answer from
    it: no ranker.server.json, nothing listening, a timeout, a non-HTTP reply on a reused port, a reply cut short,
    or a server that names another store."""
    import http.client
    try:
        with open(os.path.join(models_root(store), "ranker.server.json"), encoding="utf-8") as f:
            port = int(json.load(f)["port"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ServerDown(str(e))
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
        raise ServerDown(f"{type(e).__name__}: {e}")
    try:
        reply = json.loads(raw)
    except ValueError as e:
        raise ServerDown(f"not a ranker reply: {e}")
    if not isinstance(reply, dict) or not same_path(reply.get("p4", ""), store_root(store)):
        raise ServerDown("the server on that port is not this store's ranker")
    return status, reply


def ranker_scores(store, task, texts, timeout=RANKER_TIMEOUT_S, effort=""):
    """(scores, threshold, round, per_file, source) from this store's ranker server, or None — the JSON ranker then
    picks. `effort` (medium, high) asks the server for its node tree; a server with no tree answers from its single
    ranker, source `ranker`. A server that is down is no news; one of this store that answers wrongly is a retrain
    notice."""
    body = {"task": task, "texts": texts}
    if effort:
        body["effort"] = effort
    try:
        status, out = ranker_request(store, "/score", body, timeout)
    except ServerDown:
        return None
    try:
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {out.get('error', '')}")
        if len(out["scores"]) != len(texts) or out.get("threshold") is None:
            raise ValueError(f"the server answered {len(out['scores'])} scores for {len(texts)} rows")
        return ([float(x) for x in out["scores"]], float(out["threshold"]), out.get("round"),
                int(out.get("per_file", PER_FILE)), str(out.get("source") or "ranker"))
    except (RuntimeError, ValueError, KeyError, TypeError) as e:
        notify_retrain(store, "ranker server", e)
        return None


def ranker_health(store, timeout=2.0):
    """The /health reply of this store's ranker server ({ok, round, threshold, p4}), or None when none answers."""
    try:
        status, out = ranker_request(store, "/health", timeout=timeout)
        return out if status == 200 else None
    except ServerDown:
        return None


RANKER_PYTHON_FILE = ".ranker-python"   # models/.ranker-python: this machine's interpreter for the .pt ranker,
                                        # written by the p4-model skill's init; untracked (models/.* is ignored)


def ranker_python(store):
    """The interpreter that has phi_prune and torch: $VLDS_RANKER_PYTHON, then models/.ranker-python (local and
    untracked — never a tracked file another clone could point at an executable), then this one; None when none of
    them can import phi_prune.p4rank. A passing probe is remembered beside it, so a hook pays it once."""
    mdir = models_root(store)
    cands = [os.environ.get("VLDS_RANKER_PYTHON", "")]
    try:
        with open(os.path.join(mdir, RANKER_PYTHON_FILE), encoding="utf-8") as f:
            cands.append(f.read().strip())
    except OSError:
        pass
    cands.append(sys.executable)
    cache = os.path.join(mdir, ".ranker-python-ok")
    probe = ("import importlib.util as u, sys; "
             "sys.exit(0 if u.find_spec('torch') and (u.find_spec('phi_rank') or u.find_spec('phi_prune.p4rank')) "
             "else 3)")
    for c in dict.fromkeys(x for x in cands if x):
        try:
            stamp = f"{c}\t{os.path.getmtime(c)}"
        except OSError:
            continue
        try:
            with open(cache, encoding="utf-8") as f:
                if f.read().strip() == stamp:
                    return c
        except OSError:
            pass
        try:
            if subprocess.run([c, "-c", probe], capture_output=True, timeout=20, cwd=neutral_cwd()).returncode == 0:
                try:
                    write_atomic(cache, stamp + "\n")
                except OSError:
                    pass
                return c
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def ranker_module(py, name):
    """The module to run for `rank` or `serve` with that interpreter: phi_rank / phi_serve, or for a phi installed
    before they were split out, phi_prune.p4rank / phi_prune.p4serve."""
    new = {"rank": "phi_rank", "serve": "phi_serve"}[name]
    try:
        r = subprocess.run([py, "-c", f"import importlib.util as u, sys; sys.exit(0 if u.find_spec('{new}') else 3)"],
                           capture_output=True, timeout=20, cwd=neutral_cwd())
        if r.returncode == 0:
            return new
    except (OSError, subprocess.SubprocessError):
        pass
    return {"rank": "phi_prune.p4rank", "serve": "phi_prune.p4serve"}[name]


def ranker_checkpoint(mdir):
    """The .pt ranker's state on disk: models/ranker.pt (this machine's build), or failing that the chain's anchor
    that git keeps, models/ranker-anchor.pt, which the server rebuilds ranker.pt from."""
    state = checkpoint_state(os.path.join(mdir, "ranker.pt"))
    return state if state != "missing" else checkpoint_state(os.path.join(mdir, "ranker-anchor.pt"))


def take_lock(path, stale_s):
    """Create path exclusively (pid and time inside); a lock older than stale_s is taken over. True when held."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"{os.getpid()}\t{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) < stale_s:
                    return False
                os.remove(path)
            except OSError:
                return False
    return False


def release_lock(path):
    try:
        os.remove(path)
    except OSError:
        pass


def spawn_detached(args, cwd, log):
    """args in the background, outliving the caller, its output appended to log; the pid or None."""
    kw = {"stdin": subprocess.DEVNULL, "close_fds": True, "cwd": cwd}
    try:
        kw["stdout"] = open(log, "a", encoding="utf-8")
    except OSError:
        kw["stdout"] = subprocess.DEVNULL
    kw["stderr"] = subprocess.STDOUT
    if os.name == "nt":
        base = 0x00000200 | 0x08000000           # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        for flags in (base | 0x01000000, base):  # CREATE_BREAKAWAY_FROM_JOB first: outlive the hook's job
            try:
                return subprocess.Popen(args, creationflags=flags, **kw).pid
            except OSError:
                continue
        return None
    return subprocess.Popen(args, start_new_session=True, **kw).pid


def checkpoint_state(path):
    """missing, lfs-pointer (a clone without git-lfs: the pointer file, not the weights) or present."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return "missing"
    return "lfs-pointer" if head.startswith(b"version https://git-lfs") else "present"


SERVER_START_LOCK = ".server-start"
SERVER_START_S = 120            # one server start at a time: a start older than this is taken as failed


def ensure_server(store):
    """One line: this store's ranker server answering, started now, or why not — '' when there is no .pt yet. Never
    a second server: a start lock, and a server that is up but could not load its checkpoint is reported, not
    restarted (a restart would fail the same way)."""
    mdir = models_root(store)
    state = ranker_checkpoint(mdir)
    if state == "missing":
        return ""
    if state == "lfs-pointer":
        return ("ranker: the .pt ranker's checkpoint is a git LFS pointer, not the checkpoint — run `git lfs pull` in "
                ".claude/p4; the JSON ranker picks until then")
    h = ranker_health(store)
    if h and h.get("ok"):
        return f"ranker: round {h.get('round')} serving (models/ranker.server.json)"
    if h:
        notify_retrain(store, "ranker checkpoint", "LoadError: the server is up but could not load models/ranker.pt")
        return "ranker: the server could not load models/ranker.pt — a retrain notice is open; the JSON ranker picks"
    lock = os.path.join(mdir, SERVER_START_LOCK)
    if not take_lock(lock, SERVER_START_S):
        return "ranker: a server is already starting"
    py = ranker_python(store)
    if not py:
        release_lock(lock)
        return ("ranker: models/ranker.pt is here but no interpreter has phi_prune and torch (VLDS_RANKER_PYTHON, or "
                "models/.ranker-python which the p4-model skill's init writes) — the JSON ranker picks")
    pid = spawn_detached([py, "-m", ranker_module(py, "serve"), "--p4", store_root(store)], neutral_cwd(),
                         os.path.join(mdir, "ranker.log"))
    if not pid:
        release_lock(lock)
    return (f"ranker: server started (pid {pid}); it loads models/ranker.pt and picks from the next request, "
            "reloading whenever a retrain swaps the checkpoint" if pid else "ranker: the server failed to start")


def session_open_ranker(store):
    """The SessionStart hook's ranker line, without blocking it: a server already answering is named; otherwise the
    check and the start (probing an interpreter can take seconds) run detached, through `pick_model.py
    ensure-server`."""
    mdir = models_root(store)
    state = ranker_checkpoint(mdir)
    if state == "missing":
        return ""
    if state == "lfs-pointer":
        return ensure_server(store)
    h = ranker_health(store, timeout=1.0)
    if h and h.get("ok"):
        return f"ranker: round {h.get('round')} serving (models/ranker.server.json)"
    pid = spawn_detached([sys.executable, os.path.abspath(__file__), "--store", store, "ensure-server"], neutral_cwd(),
                         os.path.join(mdir, "ranker.log"))
    return (f"ranker: starting this store's server in the background (pid {pid}); the JSON ranker picks until it "
            "answers" if pid else "ranker: could not start the server check; the JSON ranker picks")


def cmd_ensure_server(args, store):
    print(ensure_server(store) or "ranker: no checkpoint yet")
    return 0


def ranker_seen(store):
    """The labelled pools the .pt ranker has been trained on or found nothing in (models/ranker.json `seen`), so the
    turn close and the p4-model skill owe it exactly the pools neither has met."""
    try:
        with open(os.path.join(models_root(store), "ranker.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None
    return set(meta.get("seen", meta.get("pools", [])))


def record_seen(store, ids):
    path = os.path.join(models_root(store), "ranker.json")
    try:
        with open(path, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        meta = {}
    meta["seen"] = sorted(set(meta.get("seen", [])) | set(ids))
    write_atomic(path, json.dumps(meta, indent=1) + "\n")


RANKER_TRAIN_LOCK = ".ranker-train.lock"
# the shared p4 base, shipped with the plugin (git LFS): pretrained by phi_rank on this marketplace's own public text —
# the contracts, the operator's and roboto's briefs, the flight checklists — never on any store's
SHARED_BASE = os.path.join(os.path.dirname(HERE), "models", "p4-base.pt")
RANKER_TRAIN_STALE_S = 3 * 3600


def cmd_ranker_train(args, store):
    """Export the labelled pools and train the .pt ranker on them with phi_prune.p4rank — run in the background by
    the turn close and by the p4-model skill alike, one at a time (models/.ranker-train.lock); pretraining over the
    repository's text when the base is missing, too thin or outgrown."""
    mdir = models_root(store)
    lock = os.path.join(mdir, RANKER_TRAIN_LOCK)
    if not take_lock(lock, RANKER_TRAIN_STALE_S):
        print("ranker-train — another training holds models/.ranker-train.lock; nothing started")
        return 0
    pairs = os.path.join(mdir, f".pairs.{os.getpid()}.jsonl")
    try:
        ids = {p["id"] for p in label_pools(store)}
        if not ids:
            # a fresh store: nothing to learn yet, which is no failure — the turn close trains once BOOTSTRAP_POOLS land
            print("ranker-train — no labelled pool in the store yet; nothing to learn, nothing written")
            return 0
        py = ranker_python(store)
        if not py:
            print("ranker-train — no interpreter with phi_prune and torch: set VLDS_RANKER_PYTHON, or run the p4-model "
                  "skill's init on this machine (it writes models/.ranker-python); the JSON ranker works alone")
            return 3
        pools, _data = build_pairs(store)
        if not pools:
            # labelled pools whose picks no longer match a barrier row: nothing the ranker can learn from them
            record_seen(store, ids)
            print(f"ranker-train — {len(ids)} labelled pool(s), none whose picks still match the store; nothing to "
                  "learn, recorded as seen")
            return 0
        args.jsonl = pairs
        cmd_pairs(args, store)
        mod = ranker_module(py, "rank")
        cmd = [py, "-m", mod, "train", "--p4", store_root(store), "--pairs", pairs, "--now", args.now,
               "--minutes", str(args.minutes)]
        if mod == "phi_rank" and os.path.exists(SHARED_BASE):
            cmd += ["--shared-base", SHARED_BASE]   # a store with no base of its own starts from the shared p4 base
        r = subprocess.run(cmd, cwd=neutral_cwd())
        if r.returncode != 0:
            notify_retrain(store, "ranker train", f"ExitCode: {mod} train exited {r.returncode} (its "
                                                  "output is above, or in models/ranker.log when the turn close ran it)")
            return r.returncode
        record_seen(store, ids)
        # the round wrote new out-of-fold scores: the JSON ranker learns again whether the .pt feature helps
        if os.path.exists(model_path(store, getattr(args, "model", ""))) and (load_oof(store)
                                                                            or load_oof(store, pool_effort(store))):
            tr = argparse.Namespace(now=args.now, tokens=False, model=getattr(args, "model", ""))
            cmd_train(tr, store)
        line = ensure_server(store)     # a first checkpoint gets its server now; a running one reloads on its own
        if line:
            print(line)
        return 0
    finally:
        release_lock(lock)
        try:
            os.remove(pairs)
        except OSError:
            pass


def write_picks(store, args, m):
    rows, docs, idf, avgdl = corpus(store)
    barrier, files, _spans, missing, _masks = phi.barrier_rows(store, args.session)
    state = {(r["file"], r["line"]): r["state"] for r in barrier}
    keep = [i for i, r in enumerate(rows) if state.get((r["file"], r["line"])) == "LIVE"]
    live = [rows[i] for i in keep]
    xs, _bm, shared = candidate_features(args.task, live, [docs[i] for i in keep], idf, avgdl, args.now,
                                         m.get("tokens", False))
    # the JSON ranker picks; the .pt ranker's score is one of its features when training found it helps and the
    # store's server answers — without it the feature is absent and the JSON ranker's own scale holds
    # the index's `pool-effort:` low skips the .pt; otherwise the server is asked at the effort the pt weight was
    # fitted on (the model's pt_effort: the tree at medium or high, the single ranker when unnamed), so the feature
    # keeps the scale it was learned at — a changed pool-effort reaches the picks at the JSON ranker's next train
    m["_source"] = f"json r{m.get('round', 0)}"
    if m.get("pt") and live and pool_effort(store) != "low":
        neural = ranker_scores(store, args.task, [phi.distilled(r, 400) for r in live], effort=m.get("pt_effort", ""))
        if neural:
            add_pt(xs, neural[0])
            m["_source"] += f"+pt r{neural[2]}" + (f" {neural[4]}" if neural[4].startswith("tree:") else "")
    sc = [score(m["w"], x) for x in xs]
    threshold, per_file = m["threshold"], m.get("per_file", PER_FILE)
    picked = set(select(live, sc, threshold, per_file))
    review = []
    totals = {}
    for r in barrier:
        totals[r["file"]] = totals.get(r["file"], 0) + 1
    out = []
    for fname in files:
        if fname in missing:
            continue
        # every file the barrier read gets a head, so the pool credits the model with it: a tombstone is a mask and
        # never picked, and an empty file has nothing to pick
        mine = sorted((i for i in picked if live[i]["file"] == fname), key=lambda i: -sc[i])
        out.append(f"picks (model) — {fname}, {len(mine)} of {totals.get(fname, 0)} entries bear on the task")
        for i in mine:
            terms = ", ".join(shared[i]) or "no shared term"
            out.append(f"{fname}:{live[i]['line']} || bears: model {sc[i]:.2f} ({m['_source']}); shares: {terms}")
        # the operator's review sheet: the picks and the runners-up, each with its head, so the pass can judge
        # without opening a file
        alts = sorted((i for i in range(len(live)) if live[i]["file"] == fname and i not in picked),
                      key=lambda i: -sc[i])[:REVIEW_ALTS]
        review.append(f"## {fname} — {totals.get(fname, 0)} entries; {len(mine)} model picks, {len(alts)} runners-up")
        for tag, idx in (("pick", mine), ("alt ", alts)):
            for i in idx:
                r = live[i]
                review.append(f"{tag} {fname}:{r['line']}  {sc[i]:.2f}  [{r['time'] or '(no time)'}] "
                              f"{phi.distilled(r, REVIEW_HEAD_CHARS)}")
    return out, len(picked), len(live), review


def recall_setting(store, key):
    """The value the index's `## recall` section names for `key:`, or None when unnamed."""
    idx = phi.parse_index(os.path.dirname(pt.config_index(store)))
    in_recall = False
    for l in (idx["raw"] if idx else "").split("\n"):
        if l.startswith("## "):
            in_recall = l[3:].strip().lower() == "recall"
            continue
        m = re.match(rf"^{re.escape(key)}:\s*(\S+)", l.strip()) if in_recall else None
        if m:
            return m.group(1)
    return None


def audit_every(store):
    """The index's `pool-audit:` (1 session in N runs the children beside the model), DEFAULT_AUDIT when unnamed."""
    v = recall_setting(store, "pool-audit")
    return int(v) if v and v.isdigit() else DEFAULT_AUDIT


def audit_via(store):
    """The index's `pool-audit-via:` — the agent type that reads an audit's pools in the children's seat, the teacher
    whose picks the ranker learns from on those sessions; "" (the Haiku children) when unnamed."""
    return recall_setting(store, "pool-audit-via") or ""


def pool_effort(store):
    """The index's `pool-effort:` (low, medium, high), "" when unnamed or not one of them."""
    v = (recall_setting(store, "pool-effort") or "").lower()
    return v if v in EFFORTS else ""


def audit_due(store, session):
    """Whether this session is one of the 1 in N audited: decided by its id alone, so every reader agrees."""
    n = audit_every(store)
    return n > 0 and zlib.crc32(session[:8].encode("utf-8")) % n == 0


def cmd_picks(args, store):
    path = model_path(store, args.model)
    if not os.path.exists(path):
        print(f"picks — no model at {path}: run `pick_model.py train`, or take the skeleton road")
        return 3
    m = load_model(path)
    lines, n, live, review = write_picks(store, args, m)
    text = "\n".join(lines) + "\n"
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    if args.review:
        os.makedirs(os.path.dirname(os.path.abspath(args.review)), exist_ok=True)
        with open(args.review, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# review — model round {m.get('round', 0)}; task: {args.task}\n\n" + "\n".join(review) + "\n")
    print(f"picks — {m['_source']}: {n} of {live} LIVE rows"
          + (f" → {args.out}" if args.out else "") + (f"; review sheet → {args.review}" if args.review else ""))
    if audit_due(store, args.session):
        via = audit_via(store)
        print(f"audit: this session is one of the 1 in {audit_every(store)} audited — run "
              + (f"{via} (pool-audit-via) as the audit's reader" if via else "the children")
              + " beside the model (hooks/pool-prompt.md, the model road's audit step)")
    if not args.out:
        print(text, end="")
    return 0


def cmd_label(args, store):
    """An audit's children picks as labels by content, models/labels/<session>.tsv: the virtual line numbers in a
    picks file hold only while the store stands as it is, so each pick is written as its file, time and head."""
    picks, ignored, _sources = phi.read_picks(args.picks)
    rows = {(r["file"], r["line"]): r for r in phi.barrier_rows(store, args.session)[0]}
    found = [rows[k] for k in picks if k in rows and k[0] != "tombstones.md"]
    path = os.path.join(labels_dir(store), f"{args.session[:8]}.tsv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# pick-model labels — the audit reader's picks, by file, time and head\n"
                f"# session: {args.session[:8]}\n# task: {args.task}\n# pooled: {args.now}\n# reader: {args.reader}\n")
        for r in found:
            f.write(f"{r['file']}\t{r['time'] or '(no time)'}\t{phi.distilled(r, 400)}\n")
    print(f"label — {len(found)} of {len(picks)} picks by {args.reader} written as labels"
          + (f", {ignored} line(s) ignored" if ignored else "") + f" → {path}")
    return 0


def picks_source(path):
    """Which ranker made a model picks file — `ranker rN` (the .pt server) or `json rN` — from its bears clauses."""
    try:
        with open(path, encoding="utf-8") as f:
            m = re.search(r"\((ranker r\S+|json r\S+)\)", f.read())
        return m.group(1) if m else "unknown"
    except OSError:
        return "unknown"


def cmd_shadow(args, store):
    child, _, _ = phi.read_picks(args.children)
    model, _, _ = phi.read_picks(args.model_picks)
    both = set(child) & set(model)
    rec = len(both) / len(child) if child else 0.0
    prec = len(both) / len(model) if model else 0.0
    p4 = pt.p4_of(store)
    path = os.path.join(p4 or os.path.dirname(os.path.abspath(store)), "models", "shadow.tsv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write("# pick-model shadow — time\tsession\tchildren\tmodel\tboth\trecall\tprecision\tjudge\tsource\n")
        f.write(f"{args.now}\t{args.session}\t{len(child)}\t{len(model)}\t{len(both)}\t{rec:.3f}\t{prec:.3f}\t"
                f"{args.judge}\t{picks_source(args.model_picks)}\n")
    who = "children's" if args.judge == "child" else "operator's reviewed"
    print(f"shadow — the model's picks hold {len(both)} of the {who} {len(child)} (recall {rec:.2f}); "
          f"{len(model)} model picks (precision {prec:.2f}) → {path}")
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="pick_model.py", description="VLDS pool model road")
    ap.add_argument("--store", default=os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", "p4", "vlds"))
    ap.add_argument("--model", default="", help="the model file; default <p4>/models/pick-model.json")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("pairs")
    p.add_argument("--jsonl", default="")
    p = sub.add_parser("eval")
    p.add_argument("--tokens", action="store_true", help="add the rows' own words as features")
    p.add_argument("--verbose", action="store_true")
    p = sub.add_parser("train")
    p.add_argument("--now", required=True)
    p.add_argument("--tokens", action="store_true")
    p = sub.add_parser("picks")
    p.add_argument("--session", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--now", required=True)
    p.add_argument("--out", default="")
    p.add_argument("--review", default="", help="write the operator's review sheet here: picks and runners-up, with heads")
    p = sub.add_parser("label")
    p.add_argument("--session", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--now", required=True)
    p.add_argument("--picks", required=True, help="the audit reader's picks file")
    p.add_argument("--reader", default="children", help="who picked: children, or the pool-audit-via agent type")
    p = sub.add_parser("ranker-train", help="export the pairs and train the .pt ranker (phi_prune.p4rank)")
    p.add_argument("--now", required=True)
    p.add_argument("--minutes", type=float, default=5, help="pretraining budget when the base is (re)built")
    sub.add_parser("ensure-server", help="start this store's ranker server unless one answers (detached by the hook)")
    p = sub.add_parser("shadow")
    p.add_argument("--session", required=True)
    p.add_argument("--now", required=True)
    p.add_argument("--children", required=True, help="the children's picks file")
    p.add_argument("--model-picks", required=True, help="the model's picks file")
    p.add_argument("--judge", default="child", choices=("child", "pass"),
                   help="who made the --children picks: the audit's children, or the operator's review")
    args = ap.parse_args()
    cmds = {"pairs": cmd_pairs, "eval": cmd_eval, "train": cmd_train, "picks": cmd_picks, "label": cmd_label,
            "shadow": cmd_shadow, "ranker-train": cmd_ranker_train, "ensure-server": cmd_ensure_server}
    if args.cmd not in cmds:
        ap.print_help()
        return 2
    if args.cmd in ("pairs", "eval"):
        return cmds[args.cmd](args, args.store)       # a person's command: let it fail loudly
    try:
        return cmds[args.cmd](args, args.store)
    except Exception as e:  # noqa: BLE001 — a session's model step falls back and asks for a retrain, never loops
        notify_retrain(args.store, f"pick_model {args.cmd}", e, getattr(args, "session", ""))
        print(f"{args.cmd} — the model failed ({type(e).__name__}: {e}); "
              + ("take the children road" if args.cmd == "picks" else "the model in place stays")
              + f"; a retrain notice is in models/{NOTICES} for the p4-model skill")
        return 3 if args.cmd == "picks" else 1


if __name__ == "__main__":
    sys.exit(main())
