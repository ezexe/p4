#!/usr/bin/env python3
"""p4.py: the command line of p4-phi's retrieval and of the store it reads.

  index [--force] [--repo] [--deps] [--project D]
      Rebuild the index, phi/models/index.json, when it is missing, of another version or out of date with the
      files it reads, or always with --force. --repo first brings the repository's documents up to date through
      repo.py, and --deps the documents of the project's frameworks, library packages and external modules
      through deps.py, which reads a package again when it was installed or updated.
  view [SESSION] [--backfill] [--project D] [--slug DIR ...]
      Print what a session has in view, for another session to read, or one line for each session with a record
      when none is named. --backfill builds the record of every session whose transcript is on this machine.
  said applied|set-aside|lacked [HANDLE ...] --session S [--why W]
      Record, through said.py, a session's statement about a line the prompt hook showed it this turn or about
      one it lacked.
  sync [--all] [--push] [--main B]
      Seed the store's sync workflow and its script, committing them when they were written, commit the tracked
      files the hooks changed, and merge origin's copies of this machine's branch and of main into the branch.
      --all merges every machine's branch into main instead, and --push sends the result to origin.
  labels [--from-history] [--from-transcripts] [--reexploration] [--all-sessions] [--project D] [--slug DIR ...]
      Print the label set's positives and negatives for each file and source, and the number of tasks.
      --from-history first writes the labels of the completed message rows, --from-transcripts the repo labels of
      the transcripts' turns, with --all-sessions those of transcripts no message row names too, and
      --reexploration measures the tool calls and input tokens a turn spent before it opened a file it later
      edited or cited, and how often retrieval's top 5 named that file.
  train [--if-owed] [--sources S] [--now T]
      Run one round of train.py: evaluate held out, fit, check the dictionary, write the ranker to
      phi/models/ranker.json when it passes every check of the round, and append the round to
      phi/models/eval.tsv. --if-owed returns at once unless a round is owed.
  eval [--json] [--no-dictionary] [--sources S] [--now T]
      Print the numbers of the same round, writing nothing.
  query --text T [--session S] [--now T] [--json]
      Print the retrieval lines for one message: none for an ordinary message, otherwise at most MAX_LINES, the
      line of a document of the corpus, memory or saved code shaped `- <date> <kind>: <text> (<path>:<line>)`.
  check
      Print the store's health: the corpus files' entries by state, the message rows, the vocabulary, the labels
      that name no indexed document, the counts of repo.py, deps.py, view.py and said.py, and the jargon rate of
      what retrieval would print.
  migrate --p4 TREE [--out DIR] [--apply] [--now T] [--project D] [--report F]
      Convert a store in the vlds plugin's layout into the store's files through migrate.py; without --apply it
      writes only its report.
  teacher edit-labels|dictionary|facts [--limit N] [--re-edit] [--second-opinion N] [--max-usd X] [--estimate]
          [--fake]
      Run a paid batch of teacher.py, which no hook runs. edit-labels has the teacher model keep, drop or add the
      labels of each task; dictionary writes the meaning of each pending vocabulary entry; facts answers ezexe's
      recommendation questions from the current documentation, found by web search, into phi/store/facts.md.

Every subcommand but migrate takes `--p4 <dir>`, the store's directory `.claude/p4` or the project that holds it,
and without it finds the store from CLAUDE_PROJECT_DIR or the working directory; p4conf.migrate_layout first moves
a store an older plugin wrote flat into the layout. migrate's --p4 is the tree it converts.
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
import p4conf  # noqa: E402
import ranker  # noqa: E402
import store as st  # noqa: E402

MAX_LINES = 5
PER_FILE = 2
TEXT_CHARS = 160
HISTORY_CHARS = 120
CANDIDATES = 200
# Without a trained ranker, fallback_order prints a document that passes the four gates below, or a file document
# that passes the three after them. The gates count the message's words: each word that is neither common nor a
# number, even one the index lacks, so a message about something else covers little of itself with any document.
# Looser values let general prompts such as those of silent-prompts.jsonl print, and tighter ones drop the documents
# that labelled tasks are about.
MIN_RARE = 2                  # the document holds at least this many of the message's words...
FALLBACK_COVER = 0.75         # ...they are this share of the message's words...
FALLBACK_ICOVER = 0.65        # ...their idf is this share of the message's, a word the index lacks weighing most...
FALLBACK_DENSE = 0.35         # ...and this many per square root of the document's length: a long document needs more
# A file document is a path and a symbol's name, so a question about it seldom covers FALLBACK_COVER of its own
# words with one: a file document that fails the gates above prints when it passes these three instead. A lower
# FILE_SHARED or FILE_COVER lets a general prompt print or costs precision.
FILE_SHARED = 4               # a file document: this many of the message's words...
FILE_COVER = 0.55             # ...covering this share of them...
FILE_DENSE = 0.75             # ...and making up most of the document
VARIANT_WEIGHT = 0.5          # the BM25 weight of another form of a message's word, such as committed for commits
EXPAND_WEIGHT = 0.5           # the query weight of a word that a dictionary entry's meaning adds
NODE_WEIGHT = 0.3            # the query weight of a word of the session's task, the tasks above it or their notes
NODE_TERMS = 12              # how many join the query, the rarest first, so a long brief cannot drown the message

QUERY_SETTINGS = {"max_lines": "MAX_LINES", "per_file": "PER_FILE", "text_chars": "TEXT_CHARS",
                  "history_chars": "HISTORY_CHARS", "candidates": "CANDIDATES", "min_rare": "MIN_RARE",
                  "fallback_cover": "FALLBACK_COVER", "fallback_icover": "FALLBACK_ICOVER",
                  "fallback_dense": "FALLBACK_DENSE", "file_shared": "FILE_SHARED", "file_cover": "FILE_COVER",
                  "file_dense": "FILE_DENSE", "variant_weight": "VARIANT_WEIGHT",
                  "expand_weight": "EXPAND_WEIGHT"}


def configure(p4):
    """Set the query constants that QUERY_SETTINGS maps from the section `recall.query` of the store's p4.json,
    which this reads and never writes."""
    import p4conf
    p4conf.configure(globals(), p4, "recall.query", QUERY_SETTINGS, write=False)


def clip(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


# --- the query -------------------------------------------------------------------------------------------

def history_line(idx, tok, message):
    """The line for a short message sent at least KNOWN_SHORT_MIN times before, at least once with a completed
    row: how the last completed row took it, or the two readings taken most often when the last three differ."""
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
    """The line for the newest earlier message of this session that resembles this one and has a completed row:
    what it was answered with."""
    if not session:
        return None
    rows = idx["sessions"].get(session[:8]) or idx["sessions"].get(session)
    new = set(tok.split())
    for r in reversed(rows or []):
        if r[2] and r[3] and st.resembles(new, set(r[1].split())):
            return f"- an earlier message like this one ({r[0]}) was answered: {clip(r[3], HISTORY_CHARS)}"
    return None


def dictionary_hits(idx, tok, terms):
    """The vocabulary entries whose term the message holds, each of them `on` and with its meaning written."""
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


stem = ranker.stem


def variants(idx, t):
    """The index's other forms of a word, those with the same stem. They come from the `stems` table built with the
    index, or from one built from the postings once per loaded index when the index has none."""
    m = idx.get("stems")
    if m is None:
        m = idx.get("_stems")
        if m is None:
            m = ranker.stem_table(idx["post"])
            idx["_stems"] = m
    return [v for v in m.get(stem(t), []) if v != t]


def content_terms(idx, terms):
    """The message's content words that the index holds, as they are or in another form: neither common words nor
    bare numbers."""
    return [t for t in terms if t not in st.COMMON and not t.isdigit()
            and (t in idx["post"] or variants(idx, t))]


def bm25_scores(idx, terms, weights):
    n, avgdl = idx["n"], idx["avgdl"] or 1.0
    post, docs = idx["post"], idx["docs"]
    dls = idx.get("dl") or [d["dl"] for d in docs]
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
            scores[i] = scores.get(i, 0.0) + w * idf * f * (k1 + 1) / (f + k1 * (1 - b + b * dls[i] / avgdl))
    return scores


def idf_map(idx, terms):
    n = idx["n"]
    return {t: ranker.idf_of(len(st.postings(idx, t)) // 2, n) for t in terms if t in idx["post"]}


def entry_line(d):
    if d.get("file") == "repo":                   # a path and what it names, never the file's contents
        return f"- file: {clip(d['show'], TEXT_CHARS)}" + (f" (line {d['line']})" if d.get("line", 1) > 1 else "")
    if d.get("file") == "commit":
        return f"- commit {d['time'][:10]}: {clip(d['show'], TEXT_CHARS)}"
    text = clip(d["show"], TEXT_CHARS)
    date = d["time"][:10] if d.get("time") else "undated"
    return f"- {date} {d['kind']}: {text} ({d['path']}:{d['line']})"


def superseded_ids(idx, now):
    """The ids of the facts a newer fact supersedes, unless the message is dated before that newer fact: they leave
    the candidates, so they never print."""
    sup = idx.get("sup")
    if sup is None:
        sup = [[d.get("time") or "", d["supersedes"]] for d in idx["docs"] if d.get("supersedes")]
    return {old for t, old in sup if not t or not now or t[:16] <= now[:16]}


def rank(p4, text, idx=None, model=None, k=5, now=None):
    """The ids of the top k candidates for a message, with no threshold: the trained ranker's order when there is
    one, BM25's otherwise, the dictionary's expansion applied. train.py's dictionary check and labels.py's
    re-exploration measure call it."""
    if idx is None:
        idx, _ = st.ensure_index(p4)
    if model is None:
        model = ranker.load(p4conf.sub(p4, "models", "ranker.json")) or {}
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
    cand, near_feats = near_candidates(p4, model, docs, cand, text, "", gone)
    cds = [{"file": docs[i]["file"], "kind": docs[i]["kind"], "state": docs[i]["state"], "time": docs[i]["time"],
            "toks": docs[i]["toks"].split(), "head": docs[i]["head"].split(), "dl": docs[i]["dl"],
            "fkind": docs[i].get("fkind")} for i in cand]
    extra = {"dict-hit": {j for j, i in enumerate(cand) if docs[i]["id"] in points}}
    if near_feats is not None:
        extra["near"] = near_feats
    xs, _, _ = ranker.candidate_features(qterms, cds, idf, idx["avgdl"], now, scores=[scores.get(i, 0.0) for i in cand],
                                         weights=weights, extra=extra)
    sc = [ranker.score(model["w"], x) for x in xs]
    order = sorted(range(len(cand)), key=lambda j: (-sc[j], j))
    return [docs[cand[j]]["id"] for j in order[:k]]


def near_candidates(p4, model, docs, cand, text, session, gone):
    """The candidates with near.py's documents that BM25 did not draw appended, and the `near` feature of every
    candidate among near.py's documents, when the loaded ranker was trained with that feature and p4.json's
    recall.near.on is true. The candidates as
    they are and None otherwise, or when no training round has left near.py a memory it can read."""
    if "near" not in (model or {}).get("features", []):
        return cand, None
    import near
    near.configure(p4)
    if not near.ON:                       # p4.json's recall.near.on, read by training and by the query alike
        return cand, None
    mem = near.load(p4)
    if not mem:
        return cand, None
    got = near.entries(mem, text, "", session or "")
    return near.extend(docs, near.id_index(docs), cand, got, lambda i: docs[i]["id"] not in gone)


def node_weights(idx, node, terms, weight=None, top=None):
    """The words that the session's place in the session tree adds to the query, each mapped to `weight`: the content
    words of its own task, of the tasks above it and of their notes that the index holds and the message lacks, the
    `top` rarest by idf. The gates that keep retrieval silent never count them: they only reorder and widen what the
    message's own words let through."""
    if not node:
        return {}
    weight = NODE_WEIGHT if weight is None else weight
    top = NODE_TERMS if top is None else top
    have = set(terms)
    words = [t for t in dict.fromkeys(ranker.tokens(node.text())) if t not in have]
    words = [t for t in content_terms(idx, words) if t in idx["post"]]
    n = idx["n"]
    words.sort(key=lambda t: (-ranker.idf_of(len(st.postings(idx, t)) // 2, n), t))
    return {t: weight for t in words[:top]}


def message_words(terms):
    """The message's words a line must account for: neither common words nor bare numbers, held by the index or not."""
    return [t for t in terms if t not in st.COMMON and not t.isdigit()]


def fallback_order(idx, terms, weights, points, gone, min_shared=None, cover=None, icover=None, dense=None,
                   node_ids=None):
    """The no-ranker road, taken while the store has no ranker it can read: BM25 over the message's words, their
    other forms at VARIANT_WEIGHT and the words in `weights`. A document prints when it holds at least `min_shared`
    of the message's words, each as it is or in another form, and those make up at least `cover` of the message's
    words and `icover` of their idf, with at least `dense` of them per square root of the document's length; a file
    document that misses these gates may pass on FILE_SHARED, FILE_COVER and FILE_DENSE instead. A document a
    dictionary hit points at needs no more, and one of `node_ids` needs one of the message's words. The documents
    come in the order of how many of the message's words they hold, BM25's within a tie, and standing_first puts a
    ruling in place of its same-minute correction or retraction."""
    min_shared = MIN_RARE if min_shared is None else min_shared
    cover = FALLBACK_COVER if cover is None else cover
    icover = FALLBACK_ICOVER if icover is None else icover
    dense = FALLBACK_DENSE if dense is None else dense
    docs, n = idx["docs"], idx["n"]
    q = content_terms(idx, terms)
    words = message_words(terms)
    forms = {t: [t] + variants(idx, t) for t in q}
    w = dict(weights)
    for t in q:
        for v in forms[t][1:]:
            if v not in w and v not in terms:
                w[v] = VARIANT_WEIGHT
    qterms = list(dict.fromkeys(list(terms) + list(w)))
    scores = bm25_scores(idx, qterms, w)
    cand = [i for i in sorted(scores, key=lambda i: (-scores[i], i)) if docs[i]["id"] not in gone][:CANDIDATES]
    if node_ids:
        at = idx.get("_at") or {}
        if not at:
            at = idx["_at"] = {d["id"]: i for i, d in enumerate(docs)}
        have = set(cand)
        cand += [at[e] for e in sorted(node_ids) if e in at and at[e] not in have and e not in gone]
    idf = {v: ranker.idf_of(len(st.postings(idx, v) or []) // 2, n) for t in q for v in forms[t]
           if st.postings(idx, v)}
    unseen = ranker.idf_of(0, n)
    widf = {t: max(idf.get(v, 0.0) for v in forms[t]) if t in forms else unseen for t in words}
    total = sum(widf.values()) or 1.0
    out = []
    for i in cand:
        d = docs[i]
        toks = set(d["toks"].split())
        got = [t for t in q if any(v in toks for v in forms[t])]
        c = len(got) / max(1, len(words))
        ic = sum(widf.get(t, 0.0) for t in got) / total
        dn = len(got) / max(1.0, d["dl"]) ** 0.5
        if d["id"] in points:
            out.append((i, len(q) + 1))          # a document the dictionary points at needs no more
            continue
        if node_ids and d["id"] in node_ids and got:
            out.append((i, len(got)))            # labelled for a task above the session: one shared word is enough
            continue
        if len(got) < min_shared or c < cover or ic < icover or dn < dense:
            if not (d["kind"] == "file" and len(got) >= FILE_SHARED and c >= FILE_COVER and dn >= FILE_DENSE):
                continue
        out.append((i, len(got)))
    out.sort(key=lambda x: -x[1])          # stable: BM25's order within a tie
    return standing_first(idx, [i for i, _ in out])


def standing_first(idx, order):
    """A correction or retraction written in the same minute as a ruling is the reading that ruling settled, so the
    ruling, the standing form, takes its place in the order, once, and one fact is not printed three ways."""
    rules = idx.get("rule_at")
    if rules is None:
        rules = idx["rule_at"] = st.rule_minutes(idx["docs"])
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


def live_node(p4, session):
    """The running session's place in the session tree and the documents labelled positive for the tasks of the
    sessions above it, when `recall.node.on` is set. None and an empty set when it is off or the session is unknown;
    the place and an empty set when no session is above it."""
    import p4conf
    if not p4conf.section(p4, "recall", write=False).get("node", {}).get("on"):
        return None, set()
    import node as nd
    n = nd.live(p4, session or "")
    if not n or not n.up:
        return n, set()
    tree = nd.phi_tree(p4)
    clis = {c[:8] for sid, _ in n.up for c in tree.sessions.get(sid, {}).get("cli", [])}
    import labels as lb
    tasks = {t["id"] for t in lb.read_tsv(lb.mpath(p4, lb.TASKS)) if (t.get("session") or "")[:8] in clis}
    return n, {r["entry"] for r in lb.read_tsv(lb.mpath(p4, lb.TRAIN)) if r.get("label") == "1" and r["task"] in tasks}


def query(p4, text, session=None, now=None, idx=None, model=None, node=None, node_ids=None, hide=None):
    """The retrieval lines for one message, as `{"lines": [...], "ids": [...], "jargon_dropped": n, "road": "..."}`,
    where `road` names the ways the lines came. `node` is the session's place in the session tree: the words of its
    tasks join the query at NODE_WEIGHT. `node_ids` are the documents the tasks above it were labelled with: the
    no-ranker road takes them as candidates that pass on one shared word, and a ranker trained with the `node`
    feature takes them as candidates that feature marks. `hide` names documents never printed, such as those dated
    after the message a replay asks about."""
    configure(p4)
    if idx is None:
        idx, _ = st.ensure_index(p4)
    if model is None:
        rpath = p4conf.sub(p4, "models", "ranker.json")
        model = ranker.load(rpath)
        if model is None and os.path.exists(rpath):
            # a file that is there but is no readable ranker of this kind: the no-ranker road, and a notice for the
            # p4-model skill through notices.notify, at most one a day; a failure to write it never fails the query
            try:
                import notices
                notices.notify(p4, "json ranker", ValueError("models/ranker.json is unreadable or not a p4 recall ranker"), session or "")
            except Exception:  # noqa: BLE001
                pass
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
    nw = node_weights(idx, node, terms) if node else {}
    for t, w_ in nw.items():
        weights.setdefault(t, w_)
    if nw:
        road.append("node")
    qterms = terms + [t for t in weights if t not in terms]
    if not qterms:
        return {"lines": out, "ids": ids, "jargon_dropped": dropped, "road": "+".join(road) or "no terms"}
    scores = bm25_scores(idx, qterms, weights)
    if not scores:
        return {"lines": out, "ids": ids, "jargon_dropped": dropped, "road": "+".join(road) or "no match"}
    docs = idx["docs"]
    gone = superseded_ids(idx, now) | set(hide or ())
    cand = [i for i in sorted(scores, key=lambda i: (-scores[i], i)) if docs[i]["id"] not in gone][:CANDIDATES]
    idf = idf_map(idx, qterms)
    room = MAX_LINES - len(out)
    points = {p for v in hits for p in v.get("points-at", [])}
    if model:
        road.append("ranker")
        cand, near_feats = near_candidates(p4, model, docs, cand, message, session, gone)
        cds = []
        for i in cand:
            d = docs[i]
            cds.append({"file": d["file"], "kind": d["kind"], "state": d["state"], "time": d["time"],
                        "toks": d["toks"].split(), "head": d["head"].split(), "dl": d["dl"],
                        "fkind": d.get("fkind")})
        extra = {"dict-hit": {k for k, i in enumerate(cand) if docs[i]["id"] in points}} \
            if "dict-hit" in model.get("features", []) else None
        if near_feats is not None:
            extra = {**(extra or {}), "near": near_feats}
        if node_ids and "node" in model.get("features", []):
            at = {docs[i]["id"]: k for k, i in enumerate(cand)}
            more = [i for i, d in enumerate(docs) if d["id"] in node_ids and d["id"] not in at and d["id"] not in gone]
            for i in more:
                cand.append(i)
                cds.append({"file": docs[i]["file"], "kind": docs[i]["kind"], "state": docs[i]["state"],
                            "time": docs[i]["time"], "toks": docs[i]["toks"].split(), "head": docs[i]["head"].split(),
                            "dl": docs[i]["dl"], "fkind": docs[i].get("fkind")})
            extra = {**(extra or {}), "node": {k for k, i in enumerate(cand) if docs[i]["id"] in node_ids}}
        xs, _bm, _sh = ranker.candidate_features(qterms, cds, idf, idx["avgdl"], now,
                                                 scores=[scores.get(i, 0.0) for i in cand], weights=weights, extra=extra)
        sc = [ranker.score(model["w"], x) for x in xs]
        files = [docs[i]["path"] for i in cand]
        picked = ranker.select(files, sc, model["threshold"], per_file=PER_FILE)
        order = [cand[k] for k in picked]
    else:
        road.append("bm25")
        order = fallback_order(idx, terms, weights, points, gone, node_ids=node_ids)
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
        print(f"index --repo: {s['changed']} files read again, {s['reread']} kept and {s['removed']} removed; "
              f"{s['new_commits']} new commits; {s['files']} files, {s['entries']} file documents, {s['commits']} "
              f"commits; excluded " + ", ".join(f"{k} {v}" for k, v in sorted(s["excluded"].items()))
              + (f"; {s['cut']} files past the {repo.MAX_FILE_ENTRIES:,}-document cap" if s["cut"] else ""))
    if args.deps:
        import deps
        import repo
        deps.configure(p4)
        s = deps.build(p4, args.project or repo.project_of(p4))
        print(f"index --deps: {s['packages']} packages in {s['roots']} roots, {s['read']} read again, "
              f"{s['installed']} installed, {s['updated']} updated, {s['removed']} removed; {s['entries']} documents"
              + (f"; {s['cut']} packages past the {deps.MAX_ENTRIES:,}-document cap" if s["cut"] else ""))
    if args.force or st.index_stale(p4):
        idx = st.build_index(p4)
        print(f"index: rebuilt, {idx['n']} documents -> {st.index_path(p4)}")
    else:
        print("index: fresh")
    return 0


def cmd_sync(args):
    """Seed the store's sync workflow and its script and commit them when sync.seed wrote them. Without --all, run
    `sync.py pull --snapshot`: commit the tracked files the hooks changed, then merge origin's copies of this
    machine's branch and of main into it. With --all, commit those files and run `sync.py all`, which merges every
    machine's branch into main in a worktree of its own. With --push, `pull` pushes the branch it merged into and
    `all` pushes main and moves every branch up to it; before `all`, this branch takes in origin's copy of it when
    that has commits it lacks and is pushed, and after it `sync.py catch-up` moves this branch up to the merge."""
    import p4conf
    import sync
    p4 = p4_dir(args)
    conf = p4conf.section(p4, "recall", write=False).get("sync", {})
    main = args.main or conf.get("main", "main")
    here = os.getcwd()
    os.chdir(p4)
    try:
        wrote = sync.seed(p4, main)
        if wrote:
            sync.git("add", "--", ".github")
            sync.git("-c", f"user.name={sync.NAME}", "-c", f"user.email={sync.EMAIL}", "commit", "-q", "--no-verify",
                     "-m", "p4 sync: the workflow and its script", "--", ".github")
            print("sync: seeded and committed " + ", ".join(wrote))
        if not args.all:
            return sync.main(["pull", "--snapshot", "--main", main] + (["--push"] if args.push else []))
        branch = sync.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if sync.snapshot(branch):
            print(f"sync: committed {branch}'s changed files first")
        if args.push:                         # the merge reads the remote's branches: this one has to be there
            sync.git("fetch", "-q", "origin")
            if sync.git("merge-base", "--is-ancestor", f"origin/{branch}", "HEAD", check=False).returncode != 0:
                print("\n".join(sync.merge(f"origin/{branch}", branch)))
            sync.git("push", "-q", "origin", f"HEAD:refs/heads/{branch}")
        rc = sync.main(["all", "--main", main] + (["--push"] if args.push else []))
        return rc or (sync.main(["catch-up"]) if args.push else 0)
    finally:
        os.chdir(here)


def cmd_query(args):
    p4 = p4_dir(args)
    r = query(p4, args.text, args.session, args.now or None)
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
    # a completed row: an addressed line, and a state of FRESH, ECHO or SUPERSEDED
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
    lab = p4conf.sub(p4, "models", "labels-raw.tsv")
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
              + f"; {orphan} labels name no indexed document")
    import repo
    rl = repo.stats_line(p4)
    if rl:
        print("  " + rl)
    import deps
    dl = deps.stats_line(p4)
    if dl:
        print("  " + dl)
    import view
    vl = view.stats_line(p4)
    if vl:
        print("  " + vl)
    import said
    sl = said.stats_line(p4)
    if sl:
        print("  " + sl)
    jar = sum(1 for d in idx["docs"] if not d.get("plain") and st.JARGON.search(entry_line(d)))
    rate = jar / len(idx["docs"]) if idx["docs"] else 0.0
    print(f"  index: {idx['n']} documents, {'rebuilt' if rebuilt else 'fresh'}; excluded "
          + ", ".join(f"{k} {v}" for k, v in sorted(idx.get("excluded", {}).items()))
          + f"; jargon rate of what retrieval would print {rate:.1%}, {jar} documents with jargon and no plain:; "
            f"target under 10%")
    return 0


def cmd_labels(args):
    import labels as lb
    p4 = p4_dir(args)
    if args.from_history:
        r = lb.from_history(p4)
        print(f"labels --from-history: {r['rows']} completed rows; {r['history_tasks']} tasks with "
              f"{r['history_labels']} store labels; {r['short_tasks']} short tasks with {r['short_labels']} labels")
    if args.from_transcripts:
        project = args.project or __import__("repo").project_of(p4)
        r = lb.from_transcripts(p4, project, args.slug, all_sessions=args.all_sessions)
        if r["dep_opened"]:          # dependency files the turns opened that the index lacked: read them, label again
            import deps
            deps.configure(p4)
            d = deps.build(p4, project)
            idx = st.build_index(p4)
            lb._DEP_PATHS.clear()
            print(f"labels --from-transcripts: {r['dep_opened']} dependency files the turns opened were not indexed; "
                  f"{d['read']} packages read again, the turns labelled a second time")
            r = lb.from_transcripts(p4, project, args.slug, idx=idx, all_sessions=args.all_sessions)
        print(f"labels --from-transcripts: {r['dep_rows']} of the {r['rows']} repo labels are on dependency documents")
        print(f"labels --from-transcripts: {r['transcripts']} transcripts, {r['turns']} turns, {r['matched_rows']} "
              f"of them matched to rows, {r['tasks']} tasks, {r['rows']} repo labels: "
              + ", ".join(f"{k} {v}" for k, v in sorted(r["labels"].items())))
    if args.reexploration:
        project = args.project or __import__("repo").project_of(p4)
        r = lb.reexploration(p4, project, args.slug)
        if not r["turns"]:
            print("re-exploration: no turn opened a file it later edited or cited")
        else:
            print(f"re-exploration over {r['turns']} turns: before the first relevant file was opened "
                  f"{r['calls']:.2f} tool calls and {r['tokens']:,.0f} input tokens on average; retrieval's top 5 "
                  f"named that file in {r['hit_rate']:.0%} of turns; with it, {r['cf_calls']:.2f} calls and "
                  f"{r['cf_tokens']:,.0f} tokens")
    for (f, src), (pos, neg) in sorted(lb.per_source(p4).items()):
        print(f"  {f} {src or '(none)'}: {pos} positive, {neg} negative")
    print(f"  tasks: {len(lb.read_tasks(p4))}")
    return 0


def cmd_train_eval(args, which):
    import train
    args.p4 = p4_dir(args)
    return train.cmd_train(args) if which == "train" else train.cmd_eval(args)


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
    if argv and argv[0] == "teacher":
        import teacher
        return teacher.main(argv[1:])
    ap = argparse.ArgumentParser(prog="p4.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("index")
    p.add_argument("--p4")
    p.add_argument("--force", action="store_true")
    p.add_argument("--repo", action="store_true")
    p.add_argument("--deps", action="store_true")
    p.add_argument("--project", default="")
    p = sub.add_parser("view", help="what a session has in view, for another session to read")
    p.add_argument("session", nargs="?", default="", help="a session id or its first 8 characters; none lists them")
    p.add_argument("--backfill", action="store_true", help="build the record of every session whose transcript is here")
    p.add_argument("--project", default="")
    p.add_argument("--slug", nargs="*", default=[])
    p.add_argument("--p4")
    p = sub.add_parser("said", help="a session's statement about a line it was shown, or one it lacked")
    p.add_argument("act", choices=("applied", "set-aside", "lacked"))
    p.add_argument("handles", nargs="*")
    p.add_argument("--session", required=True)
    p.add_argument("--why", default="")
    p.add_argument("--p4")
    p = sub.add_parser("sync", help="keep every machine's branch of the store in step")
    p.add_argument("--p4")
    p.add_argument("--all", action="store_true", help="merge every branch into main; with --push, move them up to it")
    p.add_argument("--push", action="store_true")
    p.add_argument("--main", default="")
    p = sub.add_parser("labels")
    p.add_argument("--p4")
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
    p = sub.add_parser("query")
    p.add_argument("--p4")
    p.add_argument("--text", required=True)
    p.add_argument("--session", default="")
    p.add_argument("--now", default="")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("check")
    p.add_argument("--p4")
    sub.add_parser("migrate", help="convert a store in the per-session layout: p4.py migrate --p4 <tree> [--out DIR] [--apply]")
    sub.add_parser("teacher", help="the paid batches: p4.py teacher edit-labels|dictionary|facts [--fake] [--max-usd X]")
    args = ap.parse_args(argv)
    if args.cmd == "index":
        return cmd_index(args)
    if args.cmd == "sync":
        return cmd_sync(args)
    if args.cmd == "view":
        import view
        if args.backfill:
            import repo
            where = p4_dir(args)
            r = view.backfill(where, args.project or repo.project_of(where), args.slug or None)
            print(f"view --backfill: {r['sessions']} sessions, {r['files']} files in their records, {r['commits']} commits, "
                  f"{r['compactions']} compactions")
            return 0
        print("\n".join(view.describe(p4_dir(args), args.session)))
        return 0
    if args.cmd == "said":
        import said
        lines, code = said.state(p4_dir(args), args.session, args.act, args.handles, args.why)
        print("\n".join(lines))
        return code
    if args.cmd == "query":
        return cmd_query(args)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "labels":
        return cmd_labels(args)
    if args.cmd in ("train", "eval"):
        return cmd_train_eval(args, args.cmd)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
