#!/usr/bin/env python3
"""prompty_eval.py: the routing step's owner and route picks measured on a store's own history, and its scorer trained.

    python -I -X utf8 prompty_eval.py --p4 <store> [--json]
    python -I -X utf8 prompty_eval.py --p4 <store> --train

It reads the store and writes nothing into it, but for `--train`, which keeps an owner scorer trained on this history
in the store's phi/models/prompty.json when it beats shared content words and naming none on held-out sessions.

The labelled set. Each kept turn of a session whose prompt is ezexe's own message and is work as routing reads work
is one example: the message, its time, and the session that received it. Its owner label is the session that ended
up doing its work:

  relayed   another session that was live at that time and took the work: the owner of the route p4-phi's gate
            kept for the message, when a later turn of the receiving session names that owner's title in its report,
            as the gate asks it to; for history kept before drafts were, a session whose later turn holds 60
            characters or more of the message. That session is the right owner. A route draft answered in the
            receiving session is here.
  new       a session started after the message for its work: the session whose brief names a start draft kept
            for the message; for older history, one whose brief holds 60 characters or more of it. No live session
            owned the work, so the right pick is none.
  here      neither: the receiving session did the work itself, so again no other live session owned it.

A scorer is given the message and the tasks of the other sessions that existed then, as the routing step is, and
picks one owner or none. It is right when it picks the labelled session, or none where the label is none.

The scorers:

  overlap   routing's fallback: the candidate whose task shares the most content words with the message, at
            OWNER_WORDS or more.
  bm25      the ranker's road with no trained model, as p4.py runs it: BM25 over ranker.tokens with idf from the
            candidates, the top candidate at a threshold chosen on the training folds.
  ranker    ranker.fit over ranker.candidate_features, trained on the other sessions' examples and tested on the
            held-out session's, the top candidate at the threshold best on the training folds.

Routes are measured the same way against the registered routes of the store: a message's route label is the route
whose topic session did its work.
"""

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import issues  # noqa: E402
import puppeteer  # noqa: E402
import ranker  # noqa: E402
import relay  # noqa: E402

QUOTE = 60                       # characters of a message a later prompt holds for it to count as quoted
FOLDS = 5


def flat(text):
    return " ".join(str(text or "").split())


def turns_of(home, sid):
    return relay._rows(os.path.join(relay._dir(home, sid), "turns.jsonl"))


def own_words(prompt):
    """True when a kept prompt is ezexe's own typing: not a handed brief, a cross-session message or an app event."""
    p = str(prompt or "").lstrip()
    return bool(p) and not p.startswith("<") and "cross-session-message" not in p and "task-notification" not in p \
        and "phi draft drf-" not in p and "phi reading grp-" not in p and "phi start request req-" not in p \
        and not p.startswith("This session is being continued from a previous conversation")


def quotes(later, message):
    m, t = flat(message), flat(later)
    if len(m) < QUOTE:
        return False
    return any(m[k:k + QUOTE] in t for k in range(0, max(1, len(m) - QUOTE + 1), 20))


def kept_words(kept, words):
    """True when a kept prompt is a draft's message: the same words, or the kept prefix of words p4-phi cut to
    TASK_CHARS with ' ...'."""
    k, w = flat(kept), flat(words)
    return k == w or (k.endswith(" ...") and len(k) > 4 and w.startswith(k[:-4].rstrip()))


def kept_label(home, sid, msg, every, rows, born, when, above):
    """The label p4-phi's own records give a message, None when no draft of the receiving session holds it, which
    leaves the quote as the fallback. A draft that started a session gives ("", "new"). A route draft gives
    (owner, "relayed") only on evidence the relay happened: a turn of the receiving session at or after the message
    whose report or said names the owner's title, as the gate asks; a route draft answered here gives ("", "here")."""
    for path in sorted(glob.glob(os.path.join(puppeteer.drafts_dir(home, sid), "*.json"))):
        d = relay._read_json(path)
        if not kept_words(msg, d.get("words")):
            continue
        if any(x.get("draft") == d.get("id") for x in every.values()):
            return "", "new"
        owner = d.get("owner") or {}
        o, title = str(owner.get("sessionId") or ""), flat(owner.get("title"))
        if d.get("verdict") == "route" and o in every and o not in above and born.get(o, "") <= when and title                 and any(str(u.get("time") or "") >= when
                        and title.lower() in flat(f"{u.get('report') or ''} {u.get('said') or ''}").lower()
                        for u in rows[sid]):
            return o, "relayed"
        return "", "here"
    return None


def closed_at(s, turns):
    """When a session left the live tree, '' while it is live: the time p4-phi kept when it counted the session as
    archived or found it archived in the app, or its last turn's when it left with no time kept."""
    for k in ("doneRetired", "stale"):
        if isinstance(s.get(k), dict) and s[k].get("time"):
            return str(s[k]["time"])
    if isinstance(s.get("archived"), str) and s["archived"]:
        return s["archived"]
    if s.get("archived") or s.get("doneRetired") or s.get("stale"):
        return str(turns[-1].get("time") or "") if turns else "0"
    return ""


def examples(home):
    """The labelled set of a store: one dict an example, with its message, time, session, label, kind and case, and
    its cands, each a session id with that session's task."""
    every = relay._sessions(home)
    rows = {sid: turns_of(home, sid) for sid in every}
    born = {sid: str(s.get("createdAt") or (rows[sid][0].get("time") if rows[sid] else "") or "") for sid, s in every.items()}
    ended = {sid: closed_at(s, rows[sid]) for sid, s in every.items()}
    out, seen = [], set()
    kids = {relay._parent(s) for s in every.values()}
    for sid, s in every.items():
        orchestrates = not relay._parent(s) or sid in kids     # routing reads a message only in an orchestrator
        for k, t in enumerate(rows[sid]):
            msg = str(t.get("prompt") or "")
            if not own_words(msg) or (k == 0 and relay._parent(s)) or (sid, flat(msg)) in seen:
                continue                           # a child's first prompt is its brief, not ezexe's message
            seen.add((sid, flat(msg)))
            if not (issues.writing(msg) and len(puppeteer.words(msg)) >= puppeteer.QUICK_WORDS):
                continue                           # routing reads only work: a question or a quick thing is left out
            when = str(t.get("time") or "")
            above, cur = set(), sid
            while cur and cur not in above:
                above.add(cur)
                cur = relay._parent(every.get(cur) or {})
            cands = [(o, flat(every[o].get("task"))) for o in every
                     if o not in above and born.get(o, "") and born[o] <= when and (not ended[o] or ended[o] > when)
                     and flat(every[o].get("task"))]
            label, kind = kept_label(home, sid, msg, every, rows, born, when, above) or ("", "here")
            for o in (every if kind == "here" else ()):
                if o in above:
                    continue
                for j, u in enumerate(rows[o]):
                    if str(u.get("time") or "") >= when and quotes(u.get("prompt"), msg):
                        if born.get(o, "") <= when and j > 0:
                            label, kind = o, "relayed"
                        elif kind != "relayed":
                            kind = "new"
                        break
                if kind == "relayed":
                    break
            if cands and orchestrates:
                out.append({"message": msg, "time": when, "session": sid, "label": label, "kind": kind,
                            "case": "others", "cands": cands})
            own = flat(s.get("task"))
            if cands and kind == "here" and own and flat(msg)[:200] not in own:
                # the same message as the session that did its work would be found from outside: the doer stands
                # among the live sessions, and the right pick is the doer
                out.append({"message": msg, "time": when, "session": sid, "label": sid, "kind": "doer",
                            "case": "doer", "cands": cands + [(sid, own)]})
    return sorted(out, key=lambda e: (e["time"], e["session"]))


# --- the scorers --------------------------------------------------------------------------------------------------------

def pick_overlap(ex, need=None):
    need = puppeteer.OWNER_WORDS if need is None else need
    best = max(((puppeteer.share(ex["message"], task)[0], sid) for sid, task in ex["cands"]), default=(0, ""))
    return best[1] if best[0] >= need else ""


def features(ex):
    """An example's candidate ids, one feature dict for each candidate and the BM25 scores, as the ranker reads them."""
    xs, bm = puppeteer.pair_features(ex["message"], [task for _, task in ex["cands"]], ex["time"])
    return [sid for sid, _ in ex["cands"]], xs, bm


def pick_scored(ids, scores, threshold):
    if not ids:
        return ""
    k = max(range(len(ids)), key=lambda i: (scores[i], -i))
    return ids[k] if scores[k] >= threshold else ""


def right(pick, ex):
    return pick == ex["label"]


def best_threshold(rows):
    """The threshold that gets the most rows right, each row the ids, the scores and the example; the higher of
    equals."""
    cuts = sorted({round(max(sc), 4) for _, sc, _ in rows if sc} | {float("inf")})
    return max(cuts, key=lambda c: (sum(right(pick_scored(ids, sc, c), ex) for ids, sc, ex in rows), c))


def folds(exs):
    sessions = sorted({e["session"] for e in exs})
    return [[s for k, s in enumerate(sessions) if k % FOLDS == f] for f in range(min(FOLDS, len(sessions)))]


def measure(exs):
    """{scorer: {right, n, false_owner, missed}} over the examples, the trained scorers cross-validated by session."""
    feats = [features(e) for e in exs]
    got = {"none named": [""] * len(exs)}
    got.update({f"overlap at {n} words": [pick_overlap(e, n) for e in exs] for n in (4, 6, 8, 12)})
    got.update({"bm25": [""] * len(exs), "ranker": [""] * len(exs)})
    for held in folds(exs):
        train = [k for k, e in enumerate(exs) if e["session"] not in held]
        test = [k for k, e in enumerate(exs) if e["session"] in held]
        if not train or not test:
            continue
        cut = best_threshold([(feats[k][0], feats[k][2], exs[k]) for k in train])
        pairs = [(x, 1 if sid == exs[k]["label"] else 0) for k in train for sid, x in zip(feats[k][0], feats[k][1])]
        w = ranker.fit(pairs) if any(y for _, y in pairs) else {}
        scored = {k: [ranker.score(w, x) for x in feats[k][1]] for k in train + test}
        rcut = best_threshold([(feats[k][0], scored[k], exs[k]) for k in train]) if w else float("inf")
        for k in test:
            got["bm25"][k] = pick_scored(feats[k][0], feats[k][2], cut)
            got["ranker"][k] = pick_scored(feats[k][0], scored[k], rcut)
    out = {}
    for name, picks in got.items():
        out[name] = {"n": len(exs), "right": sum(right(p, e) for p, e in zip(picks, exs)),
                     "false_owner": sum(1 for p, e in zip(picks, exs) if p and p != e["label"]),
                     "missed": sum(1 for p, e in zip(picks, exs) if e["label"] and p != e["label"]),
                     "owned": sum(1 for e in exs if e["label"])}
    return out


def train(exs):
    """A scorer trained on every case -> {"w", "threshold"}, None when the cases hold no right owner to learn."""
    feats = [features(e) for e in exs]
    pairs = [(x, 1 if sid == e["label"] else 0) for e, f in zip(exs, feats) for sid, x in zip(f[0], f[1])]
    if not any(y for _, y in pairs):
        return None
    w = ranker.fit(pairs)
    scored = [(f[0], [ranker.score(w, x) for x in f[1]], e) for e, f in zip(exs, feats)]
    cut = best_threshold(scored)
    return {"w": w, "threshold": 1.0 if cut == float("inf") else cut}


def keep(home, kind, model, stats):
    """A trained scorer kept in the store's phi/models/prompty.json under `kind`, "owners" or "routes"."""
    path = puppeteer.scorer_path(home)
    d = relay._read_json(path)
    if d.get("kind") != puppeteer.MODEL_KIND:
        d = {"kind": puppeteer.MODEL_KIND}
    d[kind] = {"w": {str(k): v for k, v in model["w"].items()}, "threshold": model["threshold"], **stats}
    relay._write_json(path, d)
    return path


def routes(home, exs):
    """How the registered routes fare: {routes, matched, right}, a message matched when puppeteer.score_routes ranks
    any route for it, and a route right when its topic session is the one that did the message's work."""
    every = puppeteer.all_routes(home)
    matched = hit = 0
    for e in exs:
        best = puppeteer.score_routes(home, e["message"])[:1]
        if best:
            matched += 1
            hit += int(best[0][2].get("session") in (e["label"], e["session"]))
    return {"routes": len(every), "messages": len(exs), "matched": matched, "right": hit}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--p4", required=True, help="the store whose session history is measured")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--train", action="store_true",
                    help="keep an owner scorer trained on this history in phi/models/prompty.json, only when it beats "
                         "shared content words and naming none on held-out sessions")
    a = ap.parse_args(argv)
    exs = examples(a.p4)
    others = [e for e in exs if e["case"] == "others"]
    if a.train and a.json:
        ap.error("--train prints its verdict as text")
    res = {"examples": len(exs), "kinds": {k: sum(1 for e in exs if e["kind"] == k) for k in ("relayed", "new", "here", "doer")},
           "sessions": len({e["session"] for e in exs}), "owners": measure(exs) if exs else {},
           "routes": routes(a.p4, others)}
    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    print(f"{res['examples']} cases from ezexe's messages that are work, in {res['sessions']} sessions: "
          + ", ".join(f"{v} {k}" for k, v in res["kinds"].items()))
    for name, m in res["owners"].items():
        print(f"owner by {name}: {m['right']} of {m['n']} right, {m['false_owner']} wrong owners named, "
              f"{m['missed']} of {m['owned']} owned messages missed")
    r = res["routes"]
    print(f"routes: {r['routes']} registered; matched {r['matched']} of {r['messages']} messages, "
          f"{r['right']} to the session that did the work")
    if a.train:
        m = res["owners"]
        rivals = max(m["none named"]["right"], m[f"overlap at {puppeteer.OWNER_WORDS} words"]["right"]) if m else 0
        if m and m["ranker"]["right"] > rivals:
            model = train(exs)
            print("kept: " + keep(a.p4, "owners", model, {"cases": len(exs), "right": m["ranker"]["right"]}))
        else:
            print(f"no owner scorer kept: held out, the ranker got {m['ranker']['right'] if m else 0} right and "
                  f"the better of shared content words and naming none got {rivals}; shared content words stay the "
                  f"fallback")
    return 0


if __name__ == "__main__":
    sys.exit(main())
