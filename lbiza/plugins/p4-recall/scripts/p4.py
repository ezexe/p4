#!/usr/bin/env python3
"""p4.py: the recall's one script (fresh-marketplace.md 3.4).

  index [--force] [--repo [--project D]]  rebuild models/index.json when a store, memory or src file is newer;
                                       --repo first brings the repository's entries up to date (repo.py, 4.1a)
  query --text T [--session S]         the recall lines for one message: 0 lines for an ordinary message,
                                       otherwise at most 5, each `- <date> <kind>: <text> (<file>:<line>)`
  row open|close --session S ...       stamp a message row; complete it from the reply (rows.py)
  serve-log --key K --ids ...          record what was served to a turn or a subagent (models/served/)
  usage --key K --reply-file F         the served lines' usage labels, from the reply (and --transcript)
  signals [--session S]                the dictionary's signals into vocabulary.md (pending entries)
  labels [--from-pools OLD] [--from-history] [--from-transcripts --project D --slug DIR ...] [--reexploration]
                                       list the label set with counts per source; import or derive labels
  train [--if-owed], eval              fit, evaluate held out, promote past the floor (train.py)
  dictionary check [--dry]             every vocabulary entry's two tests; a failing entry set off
  check                                store health: counts, statuses, orphan labels, the jargon rate
  migrate [--apply] ...                the old layout into the new (scripts/migrate.py)

Every subcommand takes `--p4 <dir>` (the .claude/p4 directory; default from CLAUDE_PROJECT_DIR or the cwd).
`teacher` (the paid batches, build step 9) is not built yet and exits 2.
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
MIN_RARE = 2                  # without a trained ranker a line must share this many of the message's terms...
# ...and those shared terms must carry this much idf between them, cover this share of the message's content
# terms (or at least FALLBACK_ABS of them), and be dense enough in the entry. Chosen on a held-out split (test_query.FallbackTuning, the report in
# scripts/tune_fallback.py): the pools and history labels of AudioPlugin-p4 and ap-p4_mac as the lines that should
# print, the suite's general prompts as the messages that must stay silent.
FALLBACK_IDF = 0.0            # the shared words' idf summed (the tuning found no floor that kept the cases below)
FALLBACK_TERM_IDF = 0.0       # a shared word counts only at this idf or above
FALLBACK_COVER = 0.5          # half the message's content words...
FALLBACK_ABS = 6              # ...or six of them
FALLBACK_DENSE = 0.35         # shared words per square root of the entry's length: a long entry needs more of them
# lines in the order of how many of the message's words they share, BM25 within a tie; a same-minute ruling stands in
# for its correction or retraction (standing_first). Chosen 2026-11-01 by tune_fallback.py over ap-p4_mac and
# AudioPlugin-p4 with the regression cases of test_query.Regressions as a constraint: held-out F1 0.072 (before
# 0.077), tasks with a right line 25% (before 21%), suite prompts that printed 18% (before 24%).
VARIANT_WEIGHT = 0.5          # another form of a message's word (commits / committed / commit) counts half
SUFFIXES = ("ings", "ing", "ied", "ies", "ed", "es", "s")
EXPAND_WEIGHT = 0.5
STUBS = ("teacher",)


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


def variants(idx, t):
    """The index's other forms of a word (same stem), built once per loaded index."""
    m = idx.get("_stems")
    if m is None:
        m = {}
        for w in idx["post"]:
            if w.isalpha():
                m.setdefault(stem(w), []).append(w)
        idx["_stems"] = m
    return [v for v in m.get(stem(t), []) if v != t]


def content_terms(idx, terms):
    """The message's own content words: not common, not bare numbers, and present in the index (directly or in
    another form)."""
    return [t for t in terms if t not in st.COMMON and not t.isdigit()
            and (t in idx["post"] or variants(idx, t))]


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
    if d.get("file") == "repo":                   # 4.1a: never a file's contents
        return f"- file: {clip(d['show'], TEXT_CHARS)}" + (f" (line {d['line']})" if d.get("line", 1) > 1 else "")
    if d.get("file") == "commit":
        return f"- commit {d['time'][:10]}: {clip(d['show'], TEXT_CHARS)}"
    text = clip(d["show"], TEXT_CHARS)
    date = d["time"][:10] if d.get("time") else "undated"
    return f"- {date} {d['kind']}: {text} ({d['path']}:{d['line']})"


def superseded_ids(idx, now):
    """Facts a newer fact supersedes, for a message dated after the newer one (1a): never printed."""
    out = set()
    for d in idx["docs"]:
        old = d.get("supersedes")
        if old and (not d.get("time") or not now or d["time"][:16] <= now[:16]):
            out.add(old)
    return out


def rank(p4, text, idx=None, model=None, k=5, now=None):
    """The ids of the top k candidates for a message, the threshold aside: the trained ranker's order when there is
    one, BM25's otherwise, the dictionary applied. The dictionary check and the re-exploration measure read it."""
    if idx is None:
        idx, _ = st.ensure_index(p4)
    if model is None:
        model = ranker.load(os.path.join(p4, "models", "ranker.json")) or {}
    now = now or time.strftime("%Y-%m-%d %H:%M")
    tok = st.norm_token(text)
    terms = list(dict.fromkeys(ranker.tokens(text)))
    weights = {}
    hits = dictionary_hits(idx, tok, terms)
    for v in hits:
        for t in v.get("means_toks", []):
            if t not in weights and t not in terms:
                weights[t] = EXPAND_WEIGHT
    qterms = terms + [t for t in weights if t not in terms]
    if not qterms:
        return []
    scores = bm25_scores(idx, qterms, weights)
    docs = idx["docs"]
    gone = superseded_ids(idx, now)
    cand = [i for i in sorted(scores, key=lambda i: (-scores[i], i)) if docs[i]["id"] not in gone][:CANDIDATES]
    points = {p for v in hits for p in v.get("points-at", [])}
    if not model or not model.get("w"):
        return [docs[i]["id"] for i in cand[:k]]      # BM25 over the expanded query: the expansion has to earn it
    idf = idf_map(idx, qterms)
    cds = [{"file": docs[i]["file"], "kind": docs[i]["kind"], "state": docs[i]["state"], "time": docs[i]["time"],
            "toks": docs[i]["toks"].split(), "head": docs[i]["head"].split(), "dl": docs[i]["dl"],
            "fkind": docs[i].get("fkind")} for i in cand]
    extra = {"dict-hit": {j for j, i in enumerate(cand) if docs[i]["id"] in points}}
    xs, _, _ = ranker.candidate_features(qterms, cds, idf, idx["avgdl"], now, scores=[scores[i] for i in cand],
                                         weights=weights, extra=extra)
    sc = [ranker.score(model["w"], x) for x in xs]
    order = sorted(range(len(cand)), key=lambda j: (-sc[j], j))
    return [docs[cand[j]]["id"] for j in order[:k]]


def fallback_order(idx, terms, weights, points, gone, min_shared=None, min_idf=None, cover=None, abs_n=None,
                   term_idf=None, dense=None):
    """The no-ranker road (4.5: a fresh repo): BM25 over the message's words, their other forms at half weight and
    the dictionary's expansions; a line prints when it shares at least `min_shared` of the message's content words
    (a word or another form of it), those words carry `min_idf` idf between them, and they cover `cover` of the
    message's content words or number at least `abs_n`. An entry a dictionary hit points at needs no more."""
    min_shared = MIN_RARE if min_shared is None else min_shared
    min_idf = FALLBACK_IDF if min_idf is None else min_idf
    cover = FALLBACK_COVER if cover is None else cover
    abs_n = FALLBACK_ABS if abs_n is None else abs_n
    term_idf = FALLBACK_TERM_IDF if term_idf is None else term_idf
    dense = FALLBACK_DENSE if dense is None else dense
    docs, n = idx["docs"], idx["n"]
    q = content_terms(idx, terms)
    forms = {t: [t] + variants(idx, t) for t in q}
    w = dict(weights)
    for t in q:
        for v in forms[t][1:]:
            if v not in w and v not in terms:
                w[v] = VARIANT_WEIGHT
    qterms = list(dict.fromkeys(list(terms) + list(w)))
    scores = bm25_scores(idx, qterms, w)
    cand = [i for i in sorted(scores, key=lambda i: (-scores[i], i)) if docs[i]["id"] not in gone][:CANDIDATES]
    idf = {v: ranker.idf_of(len(st.postings(idx, v) or []) // 2, n) for t in q for v in forms[t]
           if st.postings(idx, v)}
    out = []
    for i in cand:
        d = docs[i]
        if d["id"] in points:
            out.append((i, len(q) + 1))          # an entry the dictionary points at needs no more
            continue
        toks = set(d["toks"].split())
        got = [max(idf.get(v, 0.0) for v in forms[t] if v in toks) for t in q if any(v in toks for v in forms[t])]
        got = [x for x in got if x >= term_idf]
        if len(got) < min_shared or sum(got) < min_idf:
            continue
        if len(got) / max(1, len(q)) < cover and len(got) < abs_n:
            continue
        if len(got) / max(1.0, d["dl"]) ** 0.5 < dense:
            continue
        out.append((i, len(got)))
    out.sort(key=lambda x: -x[1])          # stable: BM25's order within a tie
    return standing_first(idx, [i for i, _ in out])


def standing_first(idx, order):
    """A correction or retraction written in the same minute as a ruling is the reading that ruling settled: the
    ruling, the standing form, takes its place in the order (once), so one fact is not printed three ways."""
    rules = idx.get("_rule_at")
    if rules is None:
        rules = {}
        for i, d in enumerate(idx["docs"]):
            if d["file"] == "rules.md" and d.get("time"):
                rules.setdefault(d["time"][:16], []).append(i)
        idx["_rule_at"] = rules
    out, seen = [], set()
    for i in order:
        d = idx["docs"][i]
        if d["file"] in ("corrections.md", "retractions.md") and d.get("time"):
            for r in rules.get(d["time"][:16], []):
                if r not in seen:
                    seen.add(r)
                    out.append(r)
            if rules.get(d["time"][:16]):
                continue
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


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
    gone = superseded_ids(idx, now)
    cand = [i for i in sorted(scores, key=lambda i: (-scores[i], i)) if docs[i]["id"] not in gone][:CANDIDATES]
    idf = idf_map(idx, qterms)
    room = MAX_LINES - len(out)
    points = {p for v in hits for p in v.get("points-at", [])}
    if model:
        road.append("ranker")
        cds = []
        for i in cand:
            d = docs[i]
            cds.append({"file": d["file"], "kind": d["kind"], "state": d["state"], "time": d["time"],
                        "toks": d["toks"].split(), "head": d["head"].split(), "dl": d["dl"],
                        "fkind": d.get("fkind")})
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
        order = fallback_order(idx, terms, weights, points, gone)
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
    if args.repo:
        import repo
        project = args.project or repo.project_of(p4)
        s = repo.build(p4, project)
        print(f"index --repo: {s['changed']} files read again ({s['reread']} kept, {s['removed']} removed), "
              f"{s['new_commits']} new commits; {s['files']} files, {s['entries']} file entries, {s['commits']} "
              f"commits; excluded " + ", ".join(f"{k} {v}" for k, v in sorted(s["excluded"].items()))
              + (f"; {s['cut']} files past the {repo.MAX_FILE_ENTRIES:,}-entry cap" if s["cut"] else ""))
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
    import repo
    rl = repo.stats_line(p4)
    if rl:
        print("  " + rl)
    jar = sum(1 for d in idx["docs"] if not d.get("plain") and st.JARGON.search(entry_line(d)))
    rate = jar / len(idx["docs"]) if idx["docs"] else 0.0
    print(f"  index: {idx['n']} entries ({'rebuilt' if rebuilt else 'fresh'}); excluded "
          + ", ".join(f"{k} {v}" for k, v in sorted(idx.get("excluded", {}).items()))
          + f"; jargon rate of what recall would print {rate:.1%} ({jar} entries without plain:; target under 10%)")
    return 0


def cmd_row(args):
    import rows
    p4 = p4_dir(args)
    if args.action == "open":
        print(rows.row_open(p4, args.session, args.text, args.now or None))
    else:
        reply = open(args.reply_file, encoding="utf-8").read() if args.reply_file else args.text
        e, done = rows.row_close(p4, args.session, reply, args.now or None)
        print(f"row close: {e.id if e else 'no open row'}{'' if done else ' (not completed)'}")
    return 0


def cmd_serve_log(args):
    import labels as lb
    p4 = p4_dir(args)
    lb.write_served(p4, args.key, {"ids": args.ids, "text": args.text, "task": args.task})
    print(f"serve-log: {len(args.ids)} ids -> {lb.served_path(p4, args.key)}")
    return 0


def cmd_usage(args):
    import labels as lb
    import transcript as tr
    p4 = p4_dir(args)
    served = lb.read_served(p4, args.key)
    if not served:
        print("usage: nothing was served under that key")
        return 0
    reply = open(args.reply_file, encoding="utf-8").read() if args.reply_file else ""
    turn = None
    if args.transcript:
        ts = tr.turns(args.transcript)
        turn = ts[-1] if ts else None
    idx, _ = st.ensure_index(p4)
    rows_ = lb.usage_labels(p4, idx, served, reply, turn, served.get("task", ""), time.strftime("%Y-%m-%d %H:%M"))
    if not args.dry:
        lb.append_tsv(lb.mpath(p4, lb.TRAIN), lb.TRAIN_HEAD, rows_)
    print(f"usage: {sum(1 for r in rows_ if r['label'] == '1')} used, {sum(1 for r in rows_ if r['label'] == '0')} "
          f"unused")
    return 0


def cmd_signals(args):
    import labels as lb
    p4 = p4_dir(args)
    r = lb.signals(p4, session=args.session or None, write=not args.dry)
    print(f"signals: {sum(r['signals'].values())} signals ({', '.join(f'{k} {v}' for k, v in r['signals'].items())}), "
          f"{sum(r['yielded'].values())} with a term; {r['new_terms']} new pending entries, {r['appended']} "
          f"because: lines added, {r['no_term']} without a rare term")
    return 0


def cmd_labels(args):
    import labels as lb
    p4 = p4_dir(args)
    if args.from_pools:
        r = lb.from_pools(p4, args.from_pools)
        print(f"labels --from-pools: {r['tasks']} tasks, {r['labels']} labels, {r['unresolved']} picks unresolved")
    if args.from_history:
        r = lb.from_history(p4)
        print(f"labels --from-history: {r['rows']} completed rows; {r['history_tasks']} tasks with "
              f"{r['history_labels']} store labels; {r['short_tasks']} short tasks with {r['short_labels']} labels")
    if args.from_transcripts:
        project = args.project or __import__("repo").project_of(p4)
        r = lb.from_transcripts(p4, project, args.slug, all_sessions=args.all_sessions)
        print(f"labels --from-transcripts: {r['transcripts']} transcripts, {r['turns']} turns ({r['matched_rows']} "
              f"matched to rows), {r['tasks']} tasks, {r['rows']} repo labels: "
              + ", ".join(f"{k} {v}" for k, v in sorted(r["labels"].items())))
    if args.reexploration:
        project = args.project or __import__("repo").project_of(p4)
        r = lb.reexploration(p4, project, args.slug)
        if not r["turns"]:
            print("re-exploration: no turn opened a file it later edited or cited")
        else:
            print(f"re-exploration (free half, {r['turns']} turns): before the first relevant file was opened "
                  f"{r['calls']:.2f} tool calls and {r['tokens']:,.0f} input tokens on average; recall's top 5 named "
                  f"that file in {r['hit_rate']:.0%} of turns; with it, {r['cf_calls']:.2f} calls and "
                  f"{r['cf_tokens']:,.0f} tokens")
    for (f, src), (pos, neg) in sorted(lb.per_source(p4).items()):
        print(f"  {f} {src or '(none)'}: {pos} positive, {neg} negative")
    print(f"  tasks: {len(lb.read_tasks(p4))}")
    return 0


def cmd_train_eval(args, which):
    import train
    args.p4 = p4_dir(args)
    return train.cmd_train(args) if which == "train" else train.cmd_eval(args)


def cmd_dictionary(args):
    import train
    args.p4 = p4_dir(args)
    return train.cmd_dictionary(args)


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
    p.add_argument("--repo", action="store_true")
    p.add_argument("--project", default="")
    p = sub.add_parser("row")
    p.add_argument("action", choices=("open", "close"))
    p.add_argument("--p4")
    p.add_argument("--session", required=True)
    p.add_argument("--text", default="")
    p.add_argument("--reply-file", default="")
    p.add_argument("--now", default="")
    p = sub.add_parser("serve-log")
    p.add_argument("--p4")
    p.add_argument("--key", required=True)
    p.add_argument("--ids", nargs="*", default=[])
    p.add_argument("--text", default="")
    p.add_argument("--task", default="")
    p = sub.add_parser("usage")
    p.add_argument("--p4")
    p.add_argument("--key", required=True)
    p.add_argument("--reply-file", default="")
    p.add_argument("--transcript", default="")
    p.add_argument("--dry", action="store_true")
    p = sub.add_parser("signals")
    p.add_argument("--p4")
    p.add_argument("--session", default="")
    p.add_argument("--dry", action="store_true")
    p = sub.add_parser("labels")
    p.add_argument("--p4")
    p.add_argument("--from-pools", default="")
    p.add_argument("--from-history", action="store_true")
    p.add_argument("--from-transcripts", action="store_true")
    p.add_argument("--reexploration", action="store_true")
    p.add_argument("--all-sessions", action="store_true", help="also transcripts no message row names")
    p.add_argument("--project", default="")
    p.add_argument("--slug", nargs="*", default=[])
    for name in ("train", "eval"):
        p = sub.add_parser(name)
        p.add_argument("--p4")
        p.add_argument("--now", default="")
        p.add_argument("--sources", default="")
        if name == "train":
            p.add_argument("--if-owed", action="store_true")
        else:
            p.add_argument("--json", action="store_true")
            p.add_argument("--no-dictionary", action="store_true")
    p = sub.add_parser("dictionary")
    p.add_argument("action", choices=("check",))
    p.add_argument("--p4")
    p.add_argument("--dry", action="store_true")
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
    if args.cmd == "row":
        return cmd_row(args)
    if args.cmd == "serve-log":
        return cmd_serve_log(args)
    if args.cmd == "usage":
        return cmd_usage(args)
    if args.cmd == "signals":
        return cmd_signals(args)
    if args.cmd == "labels":
        return cmd_labels(args)
    if args.cmd in ("train", "eval"):
        return cmd_train_eval(args, args.cmd)
    if args.cmd == "dictionary":
        return cmd_dictionary(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
