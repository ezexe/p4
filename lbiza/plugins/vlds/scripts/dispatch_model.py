#!/usr/bin/env python3
"""dispatch_model.py — the dispatch barrier's model: which resembling messages are plainly fresh.

The prompt hook stamps every message's dispatch row. When an earlier row of the session resembles it (the hook's
token-overlap rule), the state is left for the operator, which judges FRESH, ECHO or SUPERSEDED — one launch per
such message, though most of them are fresh asks that merely read alike. Every completed row is a label. This
script learns from them and answers one narrow question: is this resembling message so plainly fresh that the
operator need not be asked? It never proposes ECHO or SUPERSEDED: a wrong ECHO drops the owner's request, so the
model may only take the safe side, and only below a threshold under which no repeat it trained on fell.

The index's `## recall` section rules it with `dispatch-model:` — off, shadow (the hook names the model's proposal
and logs it, the operator still judges), on (the hook writes FRESH when the model is sure, and the operator judges
the rest). Unnamed, it is on once models/dispatch-model.json exists and off until then. Standard library only.

Subcommands:
  rows    the labelled rows: every turn row of every session whose state is FRESH, ECHO or SUPERSEDED and that
          the hook's rule gave at least one earlier candidate — the population the model acts on
  eval    leave-one-session-out: how many fresh rows the model would have written FRESH, and how many repeats it
          would have wrongly written FRESH (the number that must stay 0)
  train   fit on every row, set the threshold under the lowest-scored repeat, write <p4>/models/dispatch-model.json
  judge   the model's proposal for one message against the session's rows as they stand: `FRESH p=…` or `ask p=…`
  report  the shadow log (models/dispatch-shadow.tsv) joined to the rows' final states: how often a proposed FRESH
          was the operator's FRESH too
"""

import argparse
import datetime
import json
import math
import os
import re
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PLUGIN, "hooks"))
import partition as pt  # noqa: E402
import pick_model  # noqa: E402 — the fitter and the sigmoid
import vlds_hooks as vh  # noqa: E402 — the hook's own resemblance rule, tokenizer and picker shapes

DIM = 1 << 12
MARGIN = 0.4                  # the threshold sits this far under the lowest-scored repeat: at 0.5 and below no
                              # repeat was written FRESH, held out by session, on the store it was first measured on
STATES = ("FRESH", "ECHO", "SUPERSEDED")
FP_RE = re.compile(r'^- fingerprint:\s*"?(.*?)"?\s*$', re.M)
FIELD_RE = re.compile(r"^\s+([a-z-]+):\s*(.*)$", re.M)


def parse_rows(path):
    """[{fp, time, state, arrival, addressed, kind}] in file order."""
    if not os.path.exists(path):
        return []
    _header, blocks = vh.split_entries(vh.read_text(path))
    rows = []
    for b in blocks:
        m = FP_RE.search(b)
        if not m:
            continue
        f = dict(FIELD_RE.findall(b))
        m2 = re.match(r"(FRESH|ECHO|SUPERSEDED)\b(?!\s*\|)", f.get("state", "").strip())
        state = m2.group(1) if m2 else ""      # open, or the header's shape line copied as a row
        rows.append({"fp": m.group(1), "time": f.get("time", "")[:16], "state": state,
                     "arrival": f.get("arrival", ""), "addressed": bool(f.get("addressed", "").strip()),
                     "kind": f.get("kind", "")})
    return rows


def resembles(old_fp, new_tokens):
    old = set(vh._token(old_fp).split())
    return bool(old) and (old == new_tokens or (len(new_tokens) >= vh.BARRIER_MIN_TOKENS
                                                and len(old & new_tokens) / len(old | new_tokens) >= vh.BARRIER_JACCARD))


def minutes(a, b):
    try:
        return (datetime.datetime.strptime(b, vh.NOW_FMT) - datetime.datetime.strptime(a, vh.NOW_FMT)).total_seconds() / 60
    except ValueError:
        return None


def h(name):
    return zlib.crc32(name.encode("utf-8")) % DIM


def features(fp, time, earlier):
    """(x, candidates): the features of a message against the earlier rows of its session, or (None, []) when the
    hook's rule names no candidate — those messages the hook writes FRESH on its own."""
    new = set(vh._token(fp).split())
    if not new:
        return None, []
    cands = [r for r in earlier if resembles(r["fp"], new)]
    if not cands:
        return None, []
    jac = []
    for r in cands:
        old = set(vh._token(r["fp"]).split())
        jac.append(len(old & new) / len(old | new))
    best = cands[max(range(len(cands)), key=lambda i: jac[i])]
    latest = cands[-1]
    gap = minutes(latest["time"], time) if latest["time"] and time else None
    words = len(fp.split())
    x = {
        h("bias"): 1.0,
        h("jaccard-max"): max(jac),
        h("jaccard-mean"): sum(jac) / len(jac),
        h("identical"): 1.0 if max(jac) >= 0.999 else 0.0,
        h("candidates"): math.log1p(len(cands)) / 3,
        h("any-open"): 1.0 if any(not r["addressed"] for r in cands) else 0.0,
        h("latest-open"): 0.0 if latest["addressed"] else 1.0,
        h("best-repeat"): 1.0 if best["state"] in ("ECHO", "SUPERSEDED") else 0.0,
        h("words"): math.log1p(words) / 5,
        h("question"): 1.0 if "?" in fp else 0.0,
        h("picker"): 1.0 if vh.picker_shape(" ".join(fp.split())) is not None else 0.0,
        h("best-kind=" + (best["kind"] or "none")): 1.0,
    }
    if gap is None:
        x[h("no-gap")] = 1.0
    else:
        x[h("gap")] = math.log1p(max(gap, 0)) / 8
        x[h("within-10m")] = 1.0 if gap <= 10 else 0.0
    return x, cands


def session_dispatch_paths(store):
    p4 = pt.p4_of(store)
    stores = pt.session_stores(store) if p4 else [store]
    return [os.path.join(s, "dispatch.md") for s in stores if os.path.exists(os.path.join(s, "dispatch.md"))]


def model_written(store):
    """{(time, fingerprint)} of the rows the hook wrote FRESH on the model's word (`on` mode), from the
    log: those rows carry the model's verdict, not the operator's, and are never a label for it."""
    path = shadow_path(store)
    out = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for l in f:
                parts = l.rstrip("\n").split("\t", 5)
                if len(parts) == 6 and not l.startswith("#") and parts[2] == "on" and parts[3] == "FRESH":
                    out.add((parts[0], " ".join(parts[5].split())))
    return out


def labelled(store):
    """[(session dir, fingerprint, x, label, guarded)] — label 1 for ECHO or SUPERSEDED; guarded when the rule keeps
    the row the operator's whatever the model scores."""
    out = []
    mine = model_written(store)
    for path in session_dispatch_paths(store):
        rows = parse_rows(path)
        sess = os.path.basename(os.path.dirname(os.path.dirname(path)))
        for i, r in enumerate(rows):
            if r["state"] not in STATES or not r["arrival"].startswith("turn") or \
                    (r["time"], " ".join(r["fp"].split())) in mine:
                continue
            x, cands = features(r["fp"], r["time"], rows[:i])
            if x is not None:
                out.append((sess, r["fp"], x, 1 if r["state"] != "FRESH" else 0, guarded(r["fp"], cands)))
    return out


def guarded(fp, cands):
    """The rule over the model: FRESH is never written for a message identical to an earlier row, or while any
    resembling row is still open — those are the shapes an echo takes, whatever the model scores."""
    new = set(vh._token(fp).split())
    return any(not r["addressed"] for r in cands) or any(set(vh._token(r["fp"]).split()) == new for r in cands)


def threshold_for(w, examples):
    """Under the lowest score any repeat got, by MARGIN — the model writes FRESH only below every repeat it saw."""
    rep = [pick_model.score(w, x) for x, y in examples if y]
    return (min(rep) * MARGIN) if rep else 0.0


def model_path(store, given=""):
    if given:
        return given
    p4 = pt.p4_of(store)
    return os.path.join(p4 or os.path.dirname(os.path.abspath(store)), "models", "dispatch-model.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    m["w"] = {int(k): v for k, v in m["w"].items()}
    return m


def judge(store, fp, now, m):
    """(proposal, p, candidates) for a message about to be stamped, against this session's rows: FRESH when the
    model scores it under the threshold, otherwise ask (the operator's call); (None, None, 0) when the hook's rule
    names no candidate."""
    rows = parse_rows(os.path.join(store, "dispatch.md"))
    x, cands = features(fp, now, rows)
    if x is None:
        return None, None, 0
    p = pick_model.score(m["w"], x)
    return ("FRESH" if p < m["threshold"] and not guarded(fp, cands) else "ask"), p, len(cands)


def turn_rows_count(store):
    return sum(1 for path in session_dispatch_paths(store) for r in parse_rows(path)
               if r["state"] in STATES and r["arrival"].startswith("turn"))


# ─── subcommands ────────────────────────────────────────────────────────────────────────────────────────

def cmd_rows(args, store):
    data = labelled(store)
    pos = sum(r[3] for r in data)
    print(f"rows — {len(data)} resembling turn rows across {len({r[0] for r in data})} sessions: "
          f"{pos} ECHO or SUPERSEDED, {len(data) - pos} FRESH; {sum(r[4] for r in data)} kept the operator's by the "
          f"rule (identical or an open row); {turn_rows_count(store)} judged turn rows in all")
    return 0


def cmd_eval(args, store):
    data = labelled(store)
    sessions = sorted({r[0] for r in data})
    if sum(r[3] for r in data) < 2:
        print("eval — fewer than two repeats; nothing to learn")
        return 1
    saved = wrong = fresh = rep = 0
    for s in sessions:
        train = [(x, y) for ss, _fp, x, y, _g in data if ss != s]
        if not any(y for _x, y in train):
            continue
        w = pick_model.fit(train)
        t = threshold_for(w, train)
        for ss, _fp, x, y, g in data:
            if ss != s:
                continue
            writes = pick_model.score(w, x) < t and not g
            if y:
                rep += 1
                wrong += writes
            else:
                fresh += 1
                saved += writes
    print(f"eval — leave-one-session-out over {len(sessions)} sessions, {len(data)} resembling rows")
    print(f"  FRESH written by the model: {saved} of {fresh} fresh rows ({saved / max(1, fresh):.0%} of the operator "
          f"launches they cost)")
    print(f"  repeats wrongly written FRESH: {wrong} of {rep}")
    return 0


def cmd_train(args, store):
    data = labelled(store)
    examples = [(x, y) for _s, _fp, x, y, _g in data]
    if not any(y for _x, y in examples):
        print("train — no ECHO or SUPERSEDED row to learn from; nothing written")
        return 1
    w = pick_model.fit(examples)
    t = threshold_for(w, examples)
    below = sum(1 for _s, _fp, x, y, g in data if not y and not g and pick_model.score(w, x) < t)
    path = model_path(store, args.model)
    pick_model.write_atomic(path, json.dumps({"kind": "vlds dispatch model", "trained": args.now, "rows": len(examples),
                   "repeats": sum(y for _x, y in examples), "turn_rows": turn_rows_count(store),
                   "threshold": t, "w": {str(k): round(v, 6) for k, v in sorted(w.items())}}, indent=1) + "\n")
    print(f"train — {len(examples)} resembling rows, {sum(y for _x, y in examples)} repeats; threshold {t:.3f} "
          f"(FRESH for {below} of the {len(examples) - sum(y for _x, y in examples)} fresh rows it trained on) → {path}")
    return 0


def cmd_judge(args, store):
    path = model_path(store, args.model)
    if not os.path.exists(path):
        print(f"judge — no model at {path}")
        return 3
    proposal, p, n = judge(store, args.message, args.now, load(path))
    print("judge — no earlier row resembles it: the hook writes FRESH" if proposal is None
          else f"judge — {proposal} p={p:.3f} ({n} resembling row{'s' if n != 1 else ''})")
    return 0


def shadow_path(store):
    p4 = pt.p4_of(store)
    return os.path.join(p4 or os.path.dirname(os.path.abspath(store)), "models", "dispatch-shadow.tsv")


def log_shadow(store, now, sid, fp, proposal, p, mode):
    path = shadow_path(store)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write("# dispatch-model log — time\tsession\tmode\tproposal\tp\tfingerprint\n")
        f.write(f"{now}\t{sid}\t{mode}\t{proposal}\t{p:.3f}\t{' '.join(fp.split())}\n")


def cmd_report(args, store):
    path = shadow_path(store)
    if not os.path.exists(path):
        print(f"report — no log at {path}")
        return 1
    final = {}
    for dpath in session_dispatch_paths(store):
        for r in parse_rows(dpath):
            final[(r["time"], " ".join(r["fp"].split()))] = r["state"]
    agree = disagree = open_ = asked = 0
    with open(path, encoding="utf-8") as f:
        for l in f:
            if l.startswith("#") or not l.strip():
                continue
            t, _sid, _mode, proposal, _p, fp = l.rstrip("\n").split("\t", 5)
            if proposal != "FRESH":
                asked += 1
                continue
            state = final.get((t, " ".join(fp.split())))
            if state not in STATES:
                open_ += 1
            elif state == "FRESH":
                agree += 1
            else:
                disagree += 1
    print(f"report — proposed FRESH: {agree} the operator's FRESH too, {disagree} judged a repeat, {open_} not yet "
          f"judged or not found; {asked} left to the operator")
    return 0 if not disagree else 1


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="dispatch_model.py", description="VLDS dispatch barrier model")
    ap.add_argument("--store", default=os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".claude", "p4", "vlds"))
    ap.add_argument("--model", default="", help="the model file; default <p4>/models/dispatch-model.json")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("rows")
    sub.add_parser("eval")
    p = sub.add_parser("train")
    p.add_argument("--now", required=True)
    p = sub.add_parser("judge")
    p.add_argument("--message", required=True)
    p.add_argument("--now", required=True)
    sub.add_parser("report")
    args = ap.parse_args()
    cmds = {"rows": cmd_rows, "eval": cmd_eval, "train": cmd_train, "judge": cmd_judge, "report": cmd_report}
    if args.cmd not in cmds:
        ap.print_help()
        return 2
    if args.cmd in ("rows", "eval", "report"):
        return cmds[args.cmd](args, args.store)
    try:
        return cmds[args.cmd](args, args.store)
    except Exception as e:  # noqa: BLE001 — falls back to the operator and asks for a retrain, never loops
        pick_model.notify_retrain(args.store, f"dispatch_model {args.cmd}", e)
        print(f"{args.cmd} — the dispatch model failed ({type(e).__name__}: {e}); the operator judges; a retrain "
              f"notice is in models/{pick_model.NOTICES}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
