#!/usr/bin/env python3
"""ranker.py: the tokenizer, BM25, the logistic ranker's features and its fitter, ported from the old
vlds `pick_model.py` (the one model that beat word overlap: 0.379 R-precision held-out on AudioPlugin-p4 against
0.313). Standard library only, deterministic.

The model file is `models/ranker.json`:
  {"kind": "p4 recall ranker", "version": 1, "round": n, "trained": "<YYYY-MM-DD HH:MM>", "dim": 262144,
   "threshold": t, "per_file": 2, "floor": {...}, "features": ["base", ...], "w": {"<index>": weight}}
A file of any other kind (the old .pt server's `ranker.json`) is not a ranker: `load` returns None.
"""

import json
import math
import os
import re
import zlib

DIM = 1 << 18                 # hashed feature space
PER_FILE = 6                  # the old child's cap per file, kept as a feature boundary (file-top6)
TOP_EVAL = 20
EPOCHS, LR, L2 = 25, 0.1, 1e-4
RARE_IDF = 3.0                # a term rarer than this idf is a rare term
KIND = "p4 recall ranker"
BASE_FEATURES = ("bm25", "bm25-rank", "head-bm25", "file-rank", "file-top6", "top10", "overlap", "rare", "length",
                 "file=", "kind=", "state=", "age", "recent", "no-time")
EXTRA_FEATURES = ("dict-hit", "used=", "corrects")   # untested until eval shows the set at or above the base

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)+")
PART_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
STOP = frozenset("""the and for that this with from are was were not but its his her their them they you your our
into onto than then when what which who whom how why where there here have has had been being its it's out off
any all each every one two own same such only also just very more most less least over under again once both
some none nor too can will would should could may might must shall per via about after before between while
during without within upon across whose those these ever never always still yet already itself""".split())


# --- text ------------------------------------------------------------------------------------------------

def tokens(text):
    """Lower-cased words of three letters or more (and dotted numbers like 3.15, and a letter with a digit like p4),
    stop words out; a camelCase or
    snake_case name also yields its parts, so kServiceLeadMs meets 'service lead'."""
    out = []
    for t in TOKEN_RE.findall(text or ""):
        parts = [t] + [p for p in PART_RE.findall(t) if p != t] if not t[0].isdigit() else [t]
        for p in parts:
            p = p.lower()
            if (len(p) >= 3 or "." in p or len(p) == 2 and p[0].isalpha() and p[1].isdigit()) and p not in STOP:
                out.append(p)
    return out


def idf_table(docs):
    """({term: idf}, n) over token lists, BM25's idf."""
    n = len(docs)
    df = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    return {t: idf_of(c, n) for t, c in df.items()}, n


SUFFIXES = ("ings", "ing", "ied", "ies", "ed", "es", "s")


def stem(t):
    """A crude stem, enough to meet `commits` with `committed`: one suffix off, a doubled last consonant undone."""
    if not t.isalpha():
        return t
    for suf in SUFFIXES:
        if t.endswith(suf) and len(t) - len(suf) >= 4:
            t = t[:-len(suf)]
            break
    if len(t) > 4 and t[-1] == t[-2] and t[-1] not in "aeiouls":
        t = t[:-1]
    return t


def stem_table(words):
    """{stem: [words]} for the stems more than one word shares (a word alone has no other form to offer)."""
    m = {}
    for w in words:
        if w.isalpha():
            m.setdefault(stem(w), []).append(w)
    return {k: v for k, v in m.items() if len(v) > 1}


def idf_of(df, n):
    return math.log(1 + (n - df + 0.5) / (df + 0.5))


def is_rare(df, n):
    """A rare term: in under one doc in twenty (idf above RARE_IDF), or in at most two docs (a small store)."""
    return df <= 2 or idf_of(df, n) > RARE_IDF


def bm25(task_terms, doc, idf, avgdl, k1=1.2, b=0.75, weights=None):
    """BM25 of one token list against the task's terms; `weights` {term: w} scales a term (the dictionary's
    expansions count 0.5)."""
    tf = {}
    for t in doc:
        tf[t] = tf.get(t, 0) + 1
    return bm25_tf(task_terms, tf, len(doc), idf, avgdl, k1, b, weights)


def bm25_tf(task_terms, tf, dl, idf, avgdl, k1=1.2, b=0.75, weights=None):
    s = 0.0
    for t in task_terms:
        f = tf.get(t)
        if f:
            w = weights.get(t, 1.0) if weights else 1.0
            s += w * idf.get(t, 0.0) * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / (avgdl or 1.0)))
    return s


# --- features --------------------------------------------------------------------------------------------

def h(name):
    return zlib.crc32(name.encode("utf-8")) % DIM


def days_between(earlier, later):
    import datetime
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


def candidate_features(task_terms, cands, idf, avgdl, now, scores=None, weights=None, extra=None):
    """One sparse feature dict {index: value} per candidate, and the shared terms of each.

    `cands` are dicts with `file`, `kind`, `state`, `time`, `toks` (the entry's tokens) and `head` (the tokens of its
    head line, the part an old child read). `scores` are the candidates' BM25 when the caller has them.
    `extra` turns on the added features: {"dict-hit": set of candidate indices, "used": [n per candidate],
    "corrects": set of candidate indices, "near": {candidate index: (score, 1 / (1 + rank))} (near.extend)}."""
    terms = list(dict.fromkeys(task_terms))
    if scores is None:
        scores = [bm25(terms, c["toks"], idf, avgdl, weights=weights) for c in cands]
    top = max(scores, default=0.0) or 1.0
    order = sorted(range(len(cands)), key=lambda i: (-scores[i], i))
    rank = {i: k for k, i in enumerate(order)}
    head_scores = [bm25(terms, c["head"], idf, avgdl, weights=weights) for c in cands]
    head_top = max(head_scores, default=0.0) or 1.0
    file_rank, seen = {}, {}
    for i in sorted(range(len(cands)), key=lambda i: (-(scores[i] + head_scores[i]), i)):
        f = cands[i]["file"]
        file_rank[i] = seen.get(f, 0)
        seen[f] = file_rank[i] + 1
    tset = set(terms)
    out, shared_terms = [], []
    extra = extra or {}
    for i, c in enumerate(cands):
        d = c["toks"]
        shared = [t for t in dict.fromkeys(d) if t in tset]
        rare = [t for t in shared if idf.get(t, 0) > RARE_IDF]
        age = days_between(c["time"], now) if c.get("time") and now else None
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
            h("length"): math.log1p(c.get("dl", len(d))) / 5,
            h("file=" + c["file"]): 1.0,
            h("kind=" + (c.get("fkind") or c["kind"])): 1.0,
            h("state=" + c.get("state", "LIVE")): 1.0,
        }
        if age is None:
            x[h("no-time")] = 1.0
        else:
            x[h("age")] = math.log1p(age) / 4
            x[h("recent")] = 1.0 if age <= 2 else 0.0
        if "dict-hit" in extra and i in extra["dict-hit"]:
            x[h("dict-hit")] = 1.0
        if "used" in extra:
            x[h("used=")] = math.log1p(extra["used"][i]) / 3
        if "corrects" in extra and i in extra["corrects"]:
            x[h("corrects")] = 1.0
        if "near" in extra and i in extra["near"]:        # near.py: an entry earlier, similar tasks used
            nf = extra["near"][i]
            x[h("near")], x[h("near-rank")], x[h("near-hit")] = nf[0], nf[1], 1.0
            if len(nf) > 2:                               # how like the prompt that task really was
                x[h("near-like")] = nf[2]
                x[h("near-strong")] = 1.0 if nf[2] >= 0.5 else 0.0
        out.append(x)
        shared_terms.append(sorted(shared, key=lambda t: (-idf.get(t, 0), t))[:4])
    return out, scores, shared_terms


def sigmoid(z):
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def score(w, x):
    return sigmoid(sum(w.get(k, 0.0) * v for k, v in x.items()))


def fit(examples, epochs=EPOCHS, lr=LR, l2=L2, seed=0, weights=None):
    """Logistic regression by AdaGrad SGD over (x, y) pairs; positives weighed up to balance the classes.
    `weights` (one per example) scale an example's gradient: the label sources' weights of 5.5."""
    pos = sum(y for _, y in examples) or 1
    neg = len(examples) - pos or 1
    wpos = math.sqrt(neg / pos)
    import random
    w, g2 = {}, {}
    rng = random.Random(seed)
    order = list(range(len(examples)))
    for _ in range(epochs):
        rng.shuffle(order)
        for i in order:
            x, y = examples[i]
            p = score(w, x)
            grad = (p - y) * (wpos if y else 1.0) * (weights[i] if weights else 1.0)
            for k, v in x.items():
                g = grad * v + l2 * w.get(k, 0.0)
                g2[k] = g2.get(k, 0.0) + g * g
                w[k] = w.get(k, 0.0) - lr * g / math.sqrt(g2[k] + 1e-8)
    return w


# --- selection and metrics -------------------------------------------------------------------------------

def select(files, scores, threshold, per_file=PER_FILE, limit=None):
    """Indices picked: score at or above the threshold, at most per_file a file, strongest first."""
    by_file, picked = {}, []
    for i in sorted(range(len(files)), key=lambda i: (-scores[i], i)):
        if scores[i] < threshold:
            break
        n = by_file.get(files[i], 0)
        if n < per_file:
            by_file[files[i]] = n + 1
            picked.append(i)
            if limit and len(picked) >= limit:
                break
    return picked


def metrics(labels, scores, picked):
    n = sum(labels)
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    rprec = sum(labels[i] for i in order[:n]) / n if n else 0.0
    rec20 = sum(labels[i] for i in order[:TOP_EVAL]) / n if n else 0.0
    hit = sum(labels[i] for i in picked)
    prec = hit / len(picked) if picked else 0.0
    rec = hit / n if n else 0.0
    return {"r-precision": rprec, "recall@20": rec20, "precision": prec, "recall": rec,
            "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0, "picked": len(picked), "labelled": n}


def best_threshold(scored, per_file=PER_FILE, min_precision=0.6):
    """The threshold, from 0.30 to 0.95, with the best mean F1 over [(files, labels, scores)] among those whose mean
    precision is at least min_precision (4.3: a wrong line costs accuracy, so the threshold leans toward silence);
    when none reaches it, the highest-precision threshold."""
    best, best_f1, fallback, fallback_p = None, -1.0, 0.95, -1.0
    for k in range(30, 96, 5):
        t = k / 100
        ms = [metrics(lab, sc, select(fs, sc, t, per_file)) for fs, lab, sc in scored]
        f1 = mean(ms, "f1")
        p = mean(ms, "precision")
        if p >= min_precision and f1 > best_f1:
            best, best_f1 = t, f1
        if p > fallback_p:
            fallback, fallback_p = t, p
    return best if best is not None else fallback


def mean(dicts, key):
    return sum(d[key] for d in dicts) / max(1, len(dicts))


# --- the model file --------------------------------------------------------------------------------------

def load(path):
    """The ranker in `path`, its weights keyed by int, or None when absent, unreadable or not this kind."""
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m, dict) or m.get("kind") != KIND or not isinstance(m.get("w"), dict):
            return None
        m["w"] = {int(k): float(v) for k, v in m["w"].items()}
        m.setdefault("threshold", 0.5)
        m.setdefault("per_file", 2)
        m.setdefault("features", ["base"])
        return m
    except (OSError, ValueError, TypeError):
        return None


def write_atomic(path, text):
    """Write whole or not at all: a temp file beside it, then os.replace (retried while a reader holds it)."""
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
            import time
            time.sleep(min(0.002 * (attempt + 1), 0.05))


def save(path, w, threshold, round_=0, trained="", per_file=2, floor=None, features=("base",), **more):
    out = {"kind": KIND, "version": 1, "round": round_, "trained": trained, "dim": DIM, "threshold": threshold,
           "per_file": per_file, "floor": floor or {}, "features": list(features), **more,
           "w": {str(k): round(v, 6) for k, v in sorted(w.items()) if abs(v) > 1e-9}}
    write_atomic(path, json.dumps(out, indent=1) + "\n")
