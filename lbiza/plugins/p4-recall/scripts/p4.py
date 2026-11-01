#!/usr/bin/env python3
"""p4.py: the recall's one script (fresh-marketplace.md 3.4).

  index [--force]                      rebuild models/index.json when a store, memory or src file is newer
  query --text T [--session S]         the recall lines for one message: 0 lines for an ordinary message,
                                       otherwise at most 5, each `- <date> <kind>: <text> (<file>:<line>)`
  check                                store health: counts, statuses, orphan labels, the jargon rate
  migrate [--apply] ...                the old layout into the new (scripts/migrate.py)

Every subcommand takes `--p4 <dir>` (the .claude/p4 directory; default from CLAUDE_PROJECT_DIR or the cwd).
`row`, `serve-log`, `usage`, `signals`, `labels`, `train`, `eval`, `dictionary check` and `teacher` are not built yet
and exit 2.
"""

import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ranker  # noqa: E402
import store as st  # noqa: E402

MAX_LINES = 5
PER_FILE = 2
TEXT_CHARS = 160
HISTORY_CHARS = 120
CANDIDATES = 200
MIN_RARE = 2                  # without a trained ranker a line must share this many rare terms with the message
EXPAND_WEIGHT = 0.5
STUBS = ("row", "serve-log", "usage", "signals", "labels", "train", "eval", "dictionary", "teacher")


def clip(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


# --- the query (4.4, 4.5) --------------------------------------------------------------------------------

def history_line(idx, tok, message):
    """4.4 step 1: a short message seen at least twice before, with a completed row."""
    rows = idx["short"].get(tok, [])
    done = [r for r in rows if r[2] and r[3]]
    if len(rows) < st.KNOWN_SHORT_MIN or not done:
        return None
    last = done[-1]
    readings = [clip(r[3], HISTORY_CHARS) for r in done]
    taken = readings[-1]
    if len(set(readings[-3:])) > 1:
        counts = {}
        for x in readings:
            counts[x] = counts.get(x, 0) + 1
        top = sorted(counts.items(), key=lambda kv: (-kv[1], -readings[::-1].index(kv[0])))[:2]
        taken = ", ".join(f"{clip(x, 70)} (×{c})" for x, c in top)
    return (f"- you have said \"{clip(message, 60)}\" {len(rows)} times; last time ({last[0][:10]}) it was taken as: "
            f"{taken}")


def repeat_line(idx, tok, session):
    """4.4's resemblance rule: an earlier message of this session like this one, its row completed."""
    if not session:
        return None
    rows = idx["sessions"].get(session[:8]) or idx["sessions"].get(session)
    new = set(tok.split())
    for r in reversed(rows or []):
        if r[2] and r[3] and st.resembles(new, set(r[1].split())):
            return f"- an earlier message like this one ({r[0]}) was answered: {clip(r[3], HISTORY_CHARS)}"
    return None


def dictionary_hits(idx, tok, terms):
    """[vocab entry] whose term the message holds (an `on` entry with its meaning written)."""
    tset = set(terms)
    out = []
    for v in idx.get("vocab", []):
        if v.get("status", "on") != "on" or v.get("pending"):
            continue
        norm = v.get("norm", "")
        hit = bool(norm) and re.search(r"(?<!\w)" + re.escape(norm) + r"(?!\w)", tok)
        if not hit and v.get("term_toks"):
            hit = all(t in tset for t in v["term_toks"])
        if hit:
            out.append(v)
    return out


def bm25_scores(idx, terms, weights):
    n, avgdl = idx["n"], idx["avgdl"] or 1.0
    post, docs = idx["post"], idx["docs"]
    scores = {}
    k1, b = 1.2, 0.75
    for t in terms:
        p = st.postings(idx, t)
        if not p:
            continue
        idf = ranker.idf_of(len(p) // 2, n)
        w = weights.get(t, 1.0)
        for j in range(0, len(p), 2):
            i, f = p[j], p[j + 1]
            scores[i] = scores.get(i, 0.0) + w * idf * f * (k1 + 1) / (f + k1 * (1 - b + b * docs[i]["dl"] / avgdl))
    return scores


def idf_map(idx, terms):
    n = idx["n"]
    return {t: ranker.idf_of(len(st.postings(idx, t)) // 2, n) for t in terms if t in idx["post"]}


def entry_line(d):
    text = clip(d["show"], TEXT_CHARS)
    date = d["time"][:10] if d.get("time") else "undated"
    return f"- {date} {d['kind']}: {text} ({d['path']}:{d['line']})"


def query(p4, text, session=None, now=None, idx=None, model=None):
    """{"lines": [...], "ids": [...], "jargon_dropped": n, "road": "..."}: the recall for one message."""
    if idx is None:
        idx, _ = st.ensure_index(p4)
    if model is None:
        model = ranker.load(os.path.join(p4, "models", "ranker.json"))
    now = now or time.strftime("%Y-%m-%d %H:%M")
    message = (text or "").strip()
    tok = st.norm_token(message)
    out, ids, dropped, road = [], [], 0, []
    if not tok:
        return {"lines": [], "ids": [], "jargon_dropped": 0, "road": "empty"}
    short = len(tok.split()) <= st.SHORT_WORDS

    def emit(line, eid=None, plain=False):
        nonlocal dropped
        if st.JARGON.search(line) and not plain:
            dropped += 1
            return False
        out.append(line)
        if eid:
            ids.append(eid)
        return True

    seen_short = False
    if short:
        hl = history_line(idx, tok, message)
        if hl:
            seen_short = True
            road.append("history")
            emit(hl, f"history:{tok}")
    rl = repeat_line(idx, tok, session)
    if rl and rl not in out:
        road.append("repeat")
        emit(rl, "repeat")
    if seen_short or len(out) >= MAX_LINES:
        return {"lines": out[:MAX_LINES], "ids": ids, "jargon_dropped": dropped, "road": "+".join(road)}

    terms = list(dict.fromkeys(ranker.tokens(message)))
    weights = {}
    hits = dictionary_hits(idx, tok, terms)
    for v in hits:
        for t in v.get("means_toks", []):
            if t not in weights and t not in terms:
                weights[t] = EXPAND_WEIGHT
    qterms = terms + [t for t in weights if t not in terms]
    if not qterms:
        return {"lines": out, "ids": ids, "jargon_dropped": dropped, "road": "+".join(road) or "no terms"}
    scores = bm25_scores(idx, qterms, weights)
    if not scores:
        return {"lines": out, "ids": ids, "jargon_dropped": dropped, "road": "+".join(road) or "no match"}
    docs = idx["docs"]
    cand = sorted(scores, key=lambda i: (-scores[i], i))[:CANDIDATES]
    idf = idf_map(idx, qterms)
    rare_q = {t for t in qterms if t in idx["post"] and ranker.is_rare(len(st.postings(idx, t)) // 2, idx["n"])
              and t not in st.COMMON and not t.isdigit()}
    need = max(MIN_RARE, (len(rare_q) + 1) // 2)
    room = MAX_LINES - len(out)
    points = {p for v in hits for p in v.get("points-at", [])}
    if model:
        road.append("ranker")
        cds = []
        for i in cand:
            d = docs[i]
            cds.append({"file": d["file"], "kind": d["kind"], "state": d["state"], "time": d["time"],
                        "toks": d["toks"].split(), "head": d["head"].split(), "dl": d["dl"]})
        extra = {"dict-hit": {k for k, i in enumerate(cand) if docs[i]["id"] in points}} \
            if "dict-hit" in model.get("features", []) else None
        xs, _bm, _sh = ranker.candidate_features(qterms, cds, idf, idx["avgdl"], now,
                                                 scores=[scores[i] for i in cand], weights=weights, extra=extra)
        sc = [ranker.score(model["w"], x) for x in xs]
        files = [docs[i]["path"] for i in cand]
        picked = ranker.select(files, sc, model["threshold"], per_file=PER_FILE)
        order = [cand[k] for k in picked]
    else:
        road.append("bm25")
        order, per = [], {}
        for i in cand:
            d = docs[i]
            shared = set(d["toks"].split()) & rare_q
            if d["id"] not in points and len(shared) < need:   # an entry a hit term points at needs no more
                continue
            order.append(i)
    per = {}
    for i in order:
        if room <= 0:
            break
        d = docs[i]
        if per.get(d["path"], 0) >= PER_FILE:
            continue
        if emit(entry_line(d), d["id"], d.get("plain", False)):
            per[d["path"]] = per.get(d["path"], 0) + 1
            room -= 1
    return {"lines": out[:MAX_LINES], "ids": ids, "jargon_dropped": dropped, "road": "+".join(road)}


# --- subcommands -----------------------------------------------------------------------------------------

def p4_dir(args):
    p4 = st.find_p4(getattr(args, "p4", None))
    if not p4 or not os.path.isdir(p4):
        print("p4: no .claude/p4 directory found", file=sys.stderr)
        sys.exit(1)
    return p4


def cmd_index(args):
    p4 = p4_dir(args)
    if args.force or st.index_stale(p4):
        idx = st.build_index(p4)
        print(f"index: rebuilt, {idx['n']} entries -> {st.index_path(p4)}")
    else:
        print("index: fresh")
    return 0


def cmd_query(args):
    p4 = p4_dir(args)
    r = query(p4, args.text, args.session, args.now or None)
    if args.served_id and r["ids"]:
        path = os.path.join(p4, "models", "served", re.sub(r"[^\w.-]", "_", args.served_id) + ".json")
        ranker.write_atomic(path, json.dumps({"ids": r["ids"], "text": args.text[:500], "session": args.session or ""}))
    if args.json:
        print(json.dumps(r, ensure_ascii=False))
    elif r["lines"]:
        print("\n".join(r["lines"]))
    return 0


def cmd_check(args):
    p4 = p4_dir(args)
    files = st.load_store(p4)
    idx, rebuilt = st.ensure_index(p4)
    print(f"check: {p4}")
    for f in st.STORE_FILES:
        states = {}
        for e in files.get(f, []):
            states[e.state] = states.get(e.state, 0) + 1
        print(f"  {f}: {len(files.get(f, []))} entries " + ", ".join(f"{k} {v}" for k, v in sorted(states.items())))
    rows = [e for k, v in files.items() if k.startswith(st.MESSAGES + "/") for e in v]
    # completed as store_lessons.labels counts it: a state and an addressed line
    done = sum(1 for e in rows if st.completed(e)
               and re.match(r"\s*(FRESH|ECHO|SUPERSEDED)\b", e.fields.get("state", "")))
    judged = sum(1 for e in rows if re.match(r"\s*(ECHO|SUPERSEDED)", e.fields.get("state", ""))
                 or e.fields.get("match", "").strip())
    print(f"  messages: {sum(1 for k in files if k.startswith(st.MESSAGES + '/'))} sessions, {len(rows)} rows, "
          f"{done} completed, {len(rows) - done} open, {judged} judged")
    vocab = st.read_vocabulary(p4)
    print(f"  vocabulary: {len(vocab)} entries, {sum(1 for v in vocab if v['status'] == 'on' and not v['pending'])} "
          f"on, {sum(1 for v in vocab if v['pending'])} pending, {sum(1 for v in vocab if v['status'] == 'off')} off")
    ids = {d["id"] for d in idx["docs"]}
    lab = os.path.join(p4, "models", "labels-raw.tsv")
    if os.path.exists(lab):
        per, orphan = {}, 0
        with open(lab, encoding="utf-8") as f:
            next(f, None)
            for l in f:
                c = l.rstrip("\n").split("\t")
                if len(c) < 4:
                    continue
                per[c[3]] = per.get(c[3], 0) + 1
                orphan += c[1] not in ids and not c[1].startswith("archive/")
        print(f"  labels-raw.tsv: " + ", ".join(f"{k} {v}" for k, v in sorted(per.items()))
              + f"; {orphan} labels name no indexed entry")
    jar = sum(1 for d in idx["docs"] if not d.get("plain") and st.JARGON.search(entry_line(d)))
    rate = jar / len(idx["docs"]) if idx["docs"] else 0.0
    print(f"  index: {idx['n']} entries ({'rebuilt' if rebuilt else 'fresh'}); excluded "
          + ", ".join(f"{k} {v}" for k, v in sorted(idx.get("excluded", {}).items()))
          + f"; jargon rate of what recall would print {rate:.1%} ({jar} entries without plain:; target under 10%)")
    return 0


def cmd_migrate(args, rest):
    import migrate
    argv = list(rest)
    if args.p4 and "--p4" not in argv:
        argv = ["--p4", args.p4] + argv
    return migrate.main(argv)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "migrate":
        ap = argparse.ArgumentParser(prog="p4.py migrate", add_help=False)
        ap.add_argument("--p4", default=None)
        args, rest = ap.parse_known_args(argv[1:])
        return cmd_migrate(args, rest)
    if argv and argv[0] in STUBS:
        print(f"p4.py {argv[0]}: not built yet", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(prog="p4.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("index")
    p.add_argument("--p4")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("query")
    p.add_argument("--p4")
    p.add_argument("--text", required=True)
    p.add_argument("--session", default="")
    p.add_argument("--now", default="")
    p.add_argument("--served-id", default="")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("check")
    p.add_argument("--p4")
    sub.add_parser("migrate", help="old layout into new: p4.py migrate --p4 <old tree> [--out DIR] [--apply]")
    for s in STUBS:
        sub.add_parser(s, help="not built yet")
    args = ap.parse_args(argv)
    if args.cmd == "index":
        return cmd_index(args)
    if args.cmd == "query":
        return cmd_query(args)
    if args.cmd == "check":
        return cmd_check(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
