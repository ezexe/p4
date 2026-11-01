#!/usr/bin/env python3
"""tune_fallback.py: choose the no-ranker road's gate (p4.py FALLBACK_*) on a held-out split.

  python3 tune_fallback.py <p4 dir> [<p4 dir> ...] [--suite overrides_tasks.jsonl] [--history 300]

What should print: each store's pool tasks (labels-raw.tsv, source `pool`) and its history tasks (the completed rows
whose reply shares rare terms with an entry, labels.from_history, computed in memory), each a message with the
entries that bore on it. What must stay silent: the suite's general prompts (every category but `lessons`), the
messages a session would send that the store has nothing for. Tasks are split by a hash of their id: the even half
chooses the gate, the odd half reports it. The gate is the one with the best F1 of the printed lines on the tuning
half among those that print for at most 5% of the silent prompts on it; the order of the lines is BM25's, or the
number of message words matched first ("cover"), whichever the tuning half prefers.

Read-only on the stores: the history labels are computed in memory, nothing is written.
"""

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import labels as lb  # noqa: E402
import p4 as cli  # noqa: E402
import ranker  # noqa: E402
import store as st  # noqa: E402

GRID_IDF = (0.0, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 10.0)
GRID_COVER = (0.0, 0.2, 0.34, 0.5, 0.67, 0.8, 1.0)
GRID_ABS = (4, 6, 99)
GRID_DENSE = (0.0, 0.15, 0.25, 0.35)
GRID_TERM = (0.0, 1.0, 1.5, 2.5, 3.5)
SILENT_MAX = 0.05
# regression cases (the coordinator's, 2026-11-01, on ap-p4_mac): a gate is eligible only when each message recalls
# an entry whose text starts with one of the prefixes in its top 5, and the ordinary messages print nothing. They
# constrain the choice; they are not in the tuning or the held-out numbers.
MUST = (("which branch do mac commits go on", ("on this Mac the work is committed on _mac",
                                               "the Mac's branch is 0.0.1-apple&win&mac_mac")),
        ("where does the p4 repo live", ("the p4 repo is nested in the project",)))
MUST_SILENT = ("hi", "keep going", "thanks", "ok")


def half(tid):
    return int(hashlib.sha1(tid.encode()).hexdigest()[:4], 16) % 2


def candidates(idx, text):
    """[(doc index, matched, idf sum, cover, path)] in BM25 order, ungated."""
    terms = list(dict.fromkeys(ranker.tokens(text)))
    q = cli.content_terms(idx, terms)
    if not terms:
        return []
    order = cli.fallback_order(idx, terms, {}, set(), set(), min_shared=0, min_idf=0, cover=0, abs_n=0,
                               term_idf=0, dense=0)
    forms = {t: [t] + cli.variants(idx, t) for t in q}
    n = idx["n"]
    idf = {v: ranker.idf_of(len(st.postings(idx, v) or []) // 2, n) for t in q for v in forms[t]
           if st.postings(idx, v)}
    rare_q = {t for t in terms if t in idx["post"] and ranker.is_rare(len(st.postings(idx, t)) // 2, n)
              and t not in st.COMMON and not t.isdigit()}
    need = max(2, (len(rare_q) + 1) // 2)
    out = []
    for i in order:
        d = idx["docs"][i]
        toks = set(d["toks"].split())
        got = [max(idf.get(v, 0.0) for v in forms[t] if v in toks) for t in q if any(v in toks for v in forms[t])]
        out.append((i, got, len(q), d["dl"], d["path"], len(toks & rare_q) >= need))
    return out


def standing(idx, keep):
    """p4.standing_first over gated candidates: a same-minute ruling stands in for its correction or retraction,
    carrying the stats of the entry it replaced."""
    pos = {c[0]: c for c in keep}
    order = cli.standing_first(idx, [c[0] for c in keep])
    out = []
    for i in order:
        if i in pos:
            out.append(pos[i])
        else:
            d = idx["docs"][i]
            out.append((i, 0, 0, d["dl"], d["path"]))
    return out


def lines(cands, g, idx=None):
    min_idf, cover, abs_n, order, tau, dense = g
    order_standing = order != "old"
    if order == "old":                       # the gate as committed: 2 rare terms and half the message's, BM25
        keep = [c for c in cands if c[5]]    # (its candidates scored without the other word forms)
        order = "bm25"
    else:
        keep = []
        for c in cands:
            got = [x for x in c[1] if x >= tau]
            if len(got) >= 2 and sum(got) >= min_idf and (len(got) / max(1, c[2]) >= cover or len(got) >= abs_n) \
                    and len(got) / max(1.0, c[3]) ** 0.5 >= dense:
                keep.append((c[0], len(got)) + c[2:])
    if order == "cover":
        keep = sorted(keep, key=lambda c: -c[1])     # stable: BM25 within a tie
    if idx is not None and order_standing:
        keep = standing(idx, keep)
    out, per = [], {}
    for c in keep:
        if per.get(c[4], 0) >= 2:
            continue
        per[c[4]] = per.get(c[4], 0) + 1
        out.append(c[0])
        if len(out) >= 5:
            break
    return out


def score(tasks, silent, g):
    hit = printed = want = 0
    found = 0
    for idx, cands, pos in tasks:
        got = lines(cands, g, idx)
        ids = {idx["docs"][i]["id"] for i in got}
        h = len(ids & pos)
        hit += h
        printed += len(got)
        want += min(5, len(pos))
        found += h > 0
    noisy = sum(1 for idx, cands in silent if lines(cands, g, idx))
    for idx, cands in silent:
        printed += len(lines(cands, g, idx))
    p = hit / printed if printed else 0.0
    r = hit / want if want else 0.0
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0,
            "found": found / max(1, len(tasks)), "silent_broken": noisy / max(1, len(silent))}


def regressions_ok(idx_cands, g):
    for (idx, cands, prefixes) in idx_cands["must"]:
        shown = [idx["docs"][i]["show"] for i in lines(cands, g, idx)]
        if not any(x.startswith(p) for x in shown for p in prefixes):
            return False
    return all(not lines(c, g, i) for i, c in idx_cands["silent"])


def regression_data(p4_dirs):
    out = {"must": [], "silent": []}
    for p4 in p4_dirs:
        idx, _ = st.ensure_index(p4)
        if not any(d["show"].startswith(MUST[0][1][0]) for d in idx["docs"]):
            continue
        for text, prefixes in MUST:
            out["must"].append((idx, candidates(idx, text), prefixes))
        for text in MUST_SILENT:
            out["silent"].append((idx, candidates(idx, text)))
    return out


def load(p4_dirs, suite, n_history):
    by_half = {0: ([], []), 1: ([], [])}
    prompts = []
    if suite and os.path.exists(suite):
        with open(suite, encoding="utf-8") as f:
            for l in f:
                d = json.loads(l)
                if d.get("category") != "lessons":
                    prompts.append((d["id"], d["prompt"]))
    for p4 in p4_dirs:
        idx, _ = st.ensure_index(p4)
        files = st.load_store(p4)
        tasks = lb.read_tasks(p4)
        pos = {}
        for r in lb.read_tsv(lb.mpath(p4, lb.RAW)):
            if r.get("source") == "pool" and r.get("label") == "1":
                pos.setdefault(r["task"], set()).add(r["entry"])
        texts = {t: tasks[t]["text"] for t in pos if t in tasks}
        hist = history_in_memory(p4, idx, files, n_history)
        for t, (text, ents) in hist.items():
            texts[t], pos[t] = text, ents
        ids = {d["id"] for d in idx["docs"]}
        for t, text in texts.items():
            ps = pos[t] & ids
            if ps:
                by_half[half(t)][0].append((idx, candidates(idx, text), ps))
        for pid, text in prompts:
            by_half[half(pid)][1].append((idx, candidates(idx, text)))
    return by_half


def history_in_memory(p4, idx, files, limit):
    """{row id: (fingerprint, {entry ids})}: labels.from_history's rule, nothing written."""
    tmp = {}
    real_write = lb.write_tsv
    real_add = lb.add_tasks
    got = {}

    def cap_write(path, head, rows):
        for r in rows:
            if r.get("source") == "store":
                got.setdefault(r["task"], set()).add(r["entry"])

    def cap_add(p4_, rows):
        for r in rows:
            tmp[r["id"]] = r["text"]
        return 0
    lb.write_tsv, lb.add_tasks = cap_write, cap_add
    try:
        lb.from_history(p4, idx=idx, files=files)
    finally:
        lb.write_tsv, lb.add_tasks = real_write, real_add
    keys = sorted(got)[-limit:] if limit else sorted(got)
    return {k: (tmp.get(k, ""), got[k]) for k in keys if tmp.get(k)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("p4", nargs="+")
    ap.add_argument("--suite", default="/Users/ez/gritz/p4/scripts/session/overrides_tasks.jsonl")
    ap.add_argument("--history", type=int, default=300)
    a = ap.parse_args(argv)
    data = load(a.p4, a.suite, a.history)
    tune, held = data[0], data[1]
    reg = regression_data(a.p4)
    best, best_g = None, None
    floor_seen = []
    for order in ("bm25", "cover"):
        for i in GRID_IDF:
            for c in GRID_COVER:
                for n in GRID_ABS:
                  for tau in GRID_TERM:
                   for dn in GRID_DENSE:
                    g = (i, c, n, order, tau, dn)
                    m = score(tune[0], tune[1], g)
                    if reg["must"] and not regressions_ok(reg, g):
                        continue
                    floor_seen.append((m["silent_broken"], -m["f1"], g))
                    if m["silent_broken"] > SILENT_MAX:
                        continue
                    if best is None or m["f1"] > best["f1"] + 1e-12:
                        best, best_g = m, g
    if best is None and floor_seen:
        # no gate both passes the regression cases and keeps 95% of the silent prompts silent: the quietest that
        # passes, best F1 among the quietest
        floor_seen.sort()
        best_g = floor_seen[0][2]
        best = score(tune[0], tune[1], best_g)
        print(f"no gate keeps {1 - SILENT_MAX:.0%} silent while passing the regression cases; the quietest that "
              f"passes is chosen")
    print(f"regression cases: {len(reg['must'])} must recall, {len(reg['silent'])} must stay silent")
    print(f"tuning half: {len(tune[0])} tasks, {len(tune[1])} silent prompts; held-out half: {len(held[0])} tasks, "
          f"{len(held[1])} silent prompts")
    print(f"chosen gate: idf sum {best_g[0]}, each word's idf {best_g[4]}, cover {best_g[1]} or {best_g[2]} words; "
          f"order {best_g[3]}; words per root of the entry's length {best_g[5]}")
    print("  tuning  " + json.dumps({k: round(v, 3) for k, v in best.items()}))
    print("  held    " + json.dumps({k: round(v, 3) for k, v in score(held[0], held[1], best_g).items()}))
    old = (0, 0, 0, "old", 0, 0)
    if reg["must"]:
        print(f"  regression cases pass: chosen {regressions_ok(reg, best_g)}, before {regressions_ok(reg, old)}")
    print("  held, the gate before (2 shared rare terms and half the message's): "
          + json.dumps({k: round(v, 3) for k, v in score(held[0], held[1], old).items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
