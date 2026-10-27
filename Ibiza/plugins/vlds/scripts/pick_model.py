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
DEFAULT_AUDIT = 5             # `pool-audit:` unnamed — one session in five runs the children beside the model
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
    return {"path": path, "task": task.group(1).strip() if task else "", "pooled": pooled.group(1) if pooled else "",
            "session": sid, "id": sid, "picks": picks, "by_model": by_model}


def labelled_pool(p):
    """A pool the ranker may learn from: a task, a time, steering picks, and no pick of its own making."""
    return bool(p["task"] and p["pooled"] and p["picks"] and not p["by_model"])


def labels_dir(store):
    p4 = pt.p4_of(store)
    return os.path.join(p4 or os.path.dirname(os.path.abspath(store)), "models", "labels")


def parse_label_file(path):
    """An audit's labels, written by `label`: the children's picks for a task, by file, time and head."""
    task = pooled = session = ""
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
            elif l and not l.startswith("#"):
                parts = l.split("\t", 2)
                if len(parts) == 3:
                    picks.append((parts[0], parts[1], parts[2]))
    return {"path": path, "task": task, "pooled": pooled, "session": session, "id": session + "/audit",
            "picks": picks, "by_model": False}


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


def save_model(path, m):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = {**m, "w": {str(k): round(v, 6) for k, v in sorted(m["w"].items()) if abs(v) > 1e-9}}
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1)
        f.write("\n")


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
                    f.write(json.dumps({"pool": p["session"], "pooled": p["pooled"], "task": p["task"],
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
    return 0


def cmd_train(args, store):
    pools, data = build_pairs(store)
    if not pools:
        print("train — no labelled pool in the store; nothing written")
        return 1
    feats = [pool_examples(p, data, args.tokens) for p in pools]
    w = fit([(x, y) for f, p in zip(feats, pools) for x, y in zip(f[0], p["labels"])])
    t = best_threshold([([data[0][i] for i in p["rows"]], p["labels"], [score(w, x) for x in f[0]])
                        for f, p in zip(feats, pools)])
    path = model_path(store, args.model)
    old = load_model(path) if os.path.exists(path) else None
    rnd = (old.get("round", 0) + 1) if old else 0
    seen = sorted({p["id"] for p in label_pools(store)})
    save_model(path, {"kind": "vlds pick ranker", "round": rnd, "trained": args.now, "dim": DIM,
                      "tokens": bool(args.tokens), "threshold": t, "per_file": PER_FILE,
                      "pools": [p["session"] for p in pools], "seen": seen, "w": w})
    line = f"train — round {rnd}: {len(pools)} pools, {sum(p['matched'] for p in pools)} picks, threshold {t:.2f} → {path}"
    if old:
        header, payload = encode_round(old["w"], w)
        dpath = os.path.join(os.path.dirname(path), f"pick-model.r{rnd:02d}.phid")
        with open(dpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(header) + "\n" + payload)
        n = header["tensors"][0]["n_kept"]
        line += f"; delta {n} weights, {len(payload) / max(1, n):.1f} bits each → {dpath}"
    print(line)
    return 0


def write_picks(store, args, m):
    rows, docs, idf, avgdl = corpus(store)
    barrier, files, _spans, missing, _masks = phi.barrier_rows(store, args.session)
    state = {(r["file"], r["line"]): r["state"] for r in barrier}
    keep = [i for i, r in enumerate(rows) if state.get((r["file"], r["line"])) == "LIVE"]
    live = [rows[i] for i in keep]
    xs, _bm, shared = candidate_features(args.task, live, [docs[i] for i in keep], idf, avgdl, args.now,
                                         m.get("tokens", False))
    sc = [score(m["w"], x) for x in xs]
    picked = set(select(live, sc, m["threshold"], m.get("per_file", PER_FILE)))
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
            out.append(f"{fname}:{live[i]['line']} || bears: model {sc[i]:.2f}; shares: {terms}")
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


def audit_every(store):
    """The index's `pool-audit:` (1 session in N runs the children beside the model), DEFAULT_AUDIT when unnamed."""
    idx = phi.parse_index(os.path.dirname(pt.config_index(store)))
    in_recall = False
    for l in (idx["raw"] if idx else "").split("\n"):
        if l.startswith("## "):
            in_recall = l[3:].strip().lower() == "recall"
            continue
        m = re.match(r"^pool-audit:\s*(\d+)", l.strip()) if in_recall else None
        if m:
            return int(m.group(1))
    return DEFAULT_AUDIT


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
    print(f"picks — model round {m.get('round', 0)}, threshold {m['threshold']:.2f}: {n} of {live} LIVE rows"
          + (f" → {args.out}" if args.out else "") + (f"; review sheet → {args.review}" if args.review else ""))
    if audit_due(store, args.session):
        print(f"audit: this session is one of the 1 in {audit_every(store)} audited — run the children beside the "
              "model (hooks/pool-prompt.md, the model road's audit step)")
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
        f.write(f"# pick-model labels — the children's picks of an audit, by file, time and head\n"
                f"# session: {args.session[:8]}\n# task: {args.task}\n# pooled: {args.now}\n")
        for r in found:
            f.write(f"{r['file']}\t{r['time'] or '(no time)'}\t{phi.distilled(r, 400)}\n")
    print(f"label — {len(found)} of {len(picks)} children picks written as labels"
          + (f", {ignored} line(s) ignored" if ignored else "") + f" → {path}")
    return 0


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
            f.write("# pick-model shadow — time\tsession\tchildren\tmodel\tboth\trecall\tprecision\tjudge\n")
        f.write(f"{args.now}\t{args.session}\t{len(child)}\t{len(model)}\t{len(both)}\t{rec:.3f}\t{prec:.3f}\t"
                f"{args.judge}\n")
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
    p.add_argument("--picks", required=True, help="the audit children's picks file")
    p = sub.add_parser("shadow")
    p.add_argument("--session", required=True)
    p.add_argument("--now", required=True)
    p.add_argument("--children", required=True, help="the children's picks file")
    p.add_argument("--model-picks", required=True, help="the model's picks file")
    p.add_argument("--judge", default="child", choices=("child", "pass"),
                   help="who made the --children picks: the audit's children, or the operator's review")
    args = ap.parse_args()
    cmds = {"pairs": cmd_pairs, "eval": cmd_eval, "train": cmd_train, "picks": cmd_picks, "label": cmd_label,
            "shadow": cmd_shadow}
    if args.cmd not in cmds:
        ap.print_help()
        return 2
    return cmds[args.cmd](args, args.store)


if __name__ == "__main__":
    sys.exit(main())
