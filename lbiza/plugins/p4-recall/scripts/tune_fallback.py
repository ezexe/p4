#!/usr/bin/env python3
"""tune_fallback.py: choose the no-ranker road's gate (p4.py FALLBACK_*) on a held-out split.

  python3 tune_fallback.py <p4 dir> [<p4 dir> ...] [--suite overrides_tasks.jsonl] [--history 300]

What should print: each store's pool tasks (labels-raw.tsv, source `pool`) and its history tasks (the completed rows
whose reply shares rare terms with an entry, labels.from_history, computed in memory), each a message with the
entries that bore on it. What must stay silent: the suite's general prompts (every category but `lessons`), the
messages a session would send that the store has nothing for. Tasks are split by a hash of their id: the even half
chooses the gate, the odd half reports it.

The gate (p4.fallback_order): a line shares at least 2 of the message's words, covering `cover` of them and `icover`
of their idf (a word the store lacks counts at the highest idf), at `dense` shared words per root of its length.
The choice, silence first (section 0, gate 3; a wrong line costs accuracy, findings 21-22): among the gates that pass
the regression cases and leave every store's tuning-half prompts silent, those within a fifth of the best tuning F1,
and of those the one printing the fewest lines on the tuning half.

Read-only on the stores: the history labels are computed in memory, nothing is written.
"""

import argparse
import hashlib
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import labels as lb  # noqa: E402
import p4 as cli  # noqa: E402
import ranker  # noqa: E402
import store as st  # noqa: E402

GRID_COVER = (0.0, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75)
GRID_ICOVER = (0.0, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65)
GRID_DENSE = (0.0, 0.2, 0.35, 0.4, 0.45)
F1_TOLERANCE = 0.2            # a fifth of the best tuning F1 may be traded for fewer lines
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
    """[(doc index, shared, cover, icover, density)] in p4.fallback_order's candidate order, ungated."""
    terms = list(dict.fromkeys(ranker.tokens(text)))
    if not terms or not cli.content_terms(idx, terms):
        return []
    return cli.fallback_order(idx, terms, {}, set(), set(), with_stats=True)


def lines(cands, g, idx):
    """The doc indices p4.fallback_order would print under gate g = (cover, icover, dense), at most 5, 2 a file."""
    cover, icover, dense = g
    keep = [c for c in cands if c[1] >= cli.MIN_RARE and c[2] >= cover and c[3] >= icover and c[4] >= dense]
    keep.sort(key=lambda c: -c[1])           # stable: BM25 within a tie
    out, per = [], {}
    for i in cli.standing_first(idx, [c[0] for c in keep]):
        path = idx["docs"][i]["path"]
        if per.get(path, 0) >= cli.PER_FILE:
            continue
        per[path] = per.get(path, 0) + 1
        out.append(i)
        if len(out) >= cli.MAX_LINES:
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
    noisy = 0
    for idx, cands in silent:
        n = len(lines(cands, g, idx))
        printed += n
        noisy += n > 0
    p = hit / printed if printed else 0.0
    r = hit / want if want else 0.0
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0,
            "found": found / max(1, len(tasks)), "silent_broken": noisy / max(1, len(silent)), "printed": printed}


def silent_by_store(silent, g):
    """{store index id: share of its prompts that printed nothing}."""
    out = {}
    for idx, cands in silent:
        a = out.setdefault(id(idx), [0, 0])
        a[0] += not lines(cands, g, idx)
        a[1] += 1
    return {k: a / b for k, (a, b) in out.items()}


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


def choose(tune, reg):
    """The gate, silence first (module docstring); None when no gate passes the regression cases."""
    ok = []
    for g in itertools.product(GRID_COVER, GRID_ICOVER, GRID_DENSE):
        if reg["must"] and not regressions_ok(reg, g):
            continue
        if min(silent_by_store(tune[1], g).values() or [1.0]) < 1.0:
            continue
        ok.append((score(tune[0], tune[1], g), g))
    if not ok:
        return None
    best = max(m["f1"] for m, _ in ok)
    near = [(m, g) for m, g in ok if m["f1"] >= best * (1 - F1_TOLERANCE) - 1e-12]
    return min(near, key=lambda x: (x[0]["printed"], -x[0]["f1"], x[1]))[1]


def report(name, data, reg, g):
    both = data[0][1] + data[1][1]
    held = score(data[1][0], data[1][1], g)
    print(f"  {name}: held " + json.dumps({k: round(v, 3) for k, v in held.items()}))
    print(f"    every suite prompt silent, by store: "
          + ", ".join(f"{v:.0%}" for v in silent_by_store(both, g).values())
          + (f"; regression cases pass: {regressions_ok(reg, g)}" if reg["must"] else ""))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("p4", nargs="+")
    ap.add_argument("--suite", default=os.path.join(HERE, "..", "..", "..", "..", "scripts", "session",
                                                    "overrides_tasks.jsonl"))
    ap.add_argument("--history", type=int, default=300)
    a = ap.parse_args(argv)
    data = load(a.p4, a.suite, a.history)
    tune, held = data[0], data[1]
    reg = regression_data(a.p4)
    g = choose(tune, reg)
    print(f"regression cases: {len(reg['must'])} must recall, {len(reg['silent'])} must stay silent")
    print(f"tuning half: {len(tune[0])} tasks, {len(tune[1])} silent prompts; held-out half: {len(held[0])} tasks, "
          f"{len(held[1])} silent prompts")
    if g is None:
        print("no gate passes the regression cases with the tuning half silent")
        return 1
    print(f"chosen gate: cover {g[0]}, icover {g[1]}, dense {g[2]}; in p4.py: cover {cli.FALLBACK_COVER}, icover "
          f"{cli.FALLBACK_ICOVER}, dense {cli.FALLBACK_DENSE}")
    print("  tuning  " + json.dumps({k: round(v, 3) for k, v in score(tune[0], tune[1], g).items()}))
    report("chosen", data, reg, g)
    report("in p4.py", data, reg, (cli.FALLBACK_COVER, cli.FALLBACK_ICOVER, cli.FALLBACK_DENSE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
