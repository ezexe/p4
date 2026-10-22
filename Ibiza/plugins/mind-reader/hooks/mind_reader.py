#!/usr/bin/env python3
"""mind_reader.py — the mind-reader plugin's starting point: at every prompt, read the p4 vlds dispatch records
of every session in the repository, predict where this session is heading and what the owner's NEXT message will
be, and hand both to the model while it works on the current turn. The prediction is scored against the message
that actually arrives next, so the plugin measures itself.

Subcommand `predict` (UserPromptSubmit), reading the harness's JSON payload on stdin (`prompt`, `session_id`):

  corpus      every `.claude/p4/sessions/*/vlds/dispatch.md` row whose arrival is a turn (the owner's own
              messages — agent messages, task notifications and hook injections are left out), in time order per
              session; the current prompt is the session's latest turn whether or not the vlds hook stamped it yet
  next        for every corpus message that resembles the current one (token overlap), the message that FOLLOWED
              it in its own session is a candidate, weighted by the resemblance; candidates that resemble each
              other merge; the owner's adoption tokens (the most frequent short messages) fill in when nothing
              resembles. The top three are printed with their weights and where they came from
  direction   the earlier session whose run of messages most resembles this session's so far, and what that
              session went on to ask after the matching point — the road this session is likeliest to take
  score       the previous prediction for this session, read from its predictions log, is scored against the
              message that just arrived (best resemblance among its candidates), and the session's running hit
              rate is printed

Writes `.claude/p4/sessions/<name>/mind-reader/predictions.md`, one entry per prompt, in the p4 repo beside the
session's vlds store; reads nothing else and never writes a vlds file. A starting point: the resemblance is
lexical, and a judged prediction (an agent reading the pool) is the next step. Every failure prints a one-line
notice and exits 0.
"""

import json
import os
import re
import sys
import time

MIN_SIM = 0.12           # below this, a corpus message does not resemble the current one
TOP = 3
FP_MAX = 160             # characters of a message kept in a prediction
STOP = set("the a an and or to of in on for is it this that be with as at by from are was not but if so do just "
           "what when how which its can all any has have had then than into out up we you i me my your our".split())


def payload_from_stdin():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def project_root(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def tokens(text):
    return {w for w in re.findall(r"[a-z0-9][a-z0-9_.-]*", text.lower()) if len(w) > 2 and w not in STOP}


def sim(a, b):
    ta, tb = (a if isinstance(a, set) else tokens(a)), (b if isinstance(b, set) else tokens(b))
    if not ta or not tb:
        return 1.0 if (isinstance(a, str) and isinstance(b, str) and a.strip().lower() == b.strip().lower()) else 0.0
    return len(ta & tb) / len(ta | tb)


def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        v = v[1:-1]
    return v


def parse_dispatch(text):
    """[{fingerprint, time, arrival, addressed}] from a dispatch record's body — the rows after the first `---`."""
    lines = text.split("\n")
    try:
        start = lines.index("---") + 1
    except ValueError:
        return []
    rows, row = [], None
    for ln in lines[start:]:
        if ln.startswith("- fingerprint:"):
            if row:
                rows.append(row)
            row = {"fingerprint": unquote(ln[len("- fingerprint:"):])}
        elif row is not None and ln.startswith("  ") and ":" in ln:
            k, v = ln.strip().split(":", 1)
            if k in ("time", "arrival", "addressed"):
                row[k] = v.strip()
    if row:
        rows.append(row)
    return rows


def is_owner(row):
    fp = row.get("fingerprint", "")
    return row.get("arrival", "").startswith("turn") and not fp.startswith("<") and fp.strip() != ""


def sessions_dir(root):
    return os.path.join(root, ".claude", "p4", "sessions")


def session_name(root, sid):
    s8 = (sid or "unknown")[:8]
    try:
        return next((n for n in os.listdir(sessions_dir(root)) if n == s8 or n.endswith("--" + s8)), s8)
    except OSError:
        return s8


def load_corpus(root):
    """{session name: [owner rows in time order]}"""
    out = {}
    base = sessions_dir(root)
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for name in names:
        path = os.path.join(base, name, "vlds", "dispatch.md")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            rows = [r for r in parse_dispatch(f.read()) if is_owner(r)]
        rows.sort(key=lambda r: r.get("time", ""))
        if rows:
            out[name] = rows
    return out


def current_run(corpus, name, prompt):
    """This session's owner messages so far, ending in the current prompt (stamped or not)."""
    run = [r["fingerprint"] for r in corpus.get(name, [])]
    if run and stamped(run[-1], prompt):
        run[-1] = prompt
    else:
        run.append(prompt)
    return run


def stamped(fingerprint, prompt):
    """True when a dispatch fingerprint is the prompt's own stamp (the hook keeps its opening, maybe cut)."""
    fp = " ".join(fingerprint.rstrip("…").split()).lower()
    return bool(fp) and " ".join(prompt.split()).lower().startswith(fp)


def short(text):
    text = " ".join(text.split())
    return text if len(text) <= FP_MAX else text[:FP_MAX - 1] + "…"


def predict_next(corpus, name, prompt):
    """[(weight, message, source)] — the followers of every message that resembles the prompt, merged."""
    tp = tokens(prompt)
    cands = []
    for sname, rows in corpus.items():
        for i in range(len(rows) - 1):
            if sname == name and stamped(rows[i]["fingerprint"], prompt):
                continue                       # the current prompt's own stamp
            s = sim(tp, rows[i]["fingerprint"])
            if s >= MIN_SIM:
                cands.append([s, rows[i + 1]["fingerprint"], f"{sname} @ {rows[i + 1].get('time', '?')}"])
    merged = []
    for c in sorted(cands, key=lambda c: -c[0]):
        for m in merged:
            if sim(m[1], c[1]) >= 0.6:
                m[0] += c[0]
                break
        else:
            merged.append(c)
    merged.sort(key=lambda c: -c[0])
    if len(merged) < TOP:                      # the owner's adoption tokens: the most frequent short messages
        counts = {}
        for rows in corpus.values():
            for r in rows:
                fp = r["fingerprint"].strip().lower()
                if 0 < len(fp.split()) <= 3:
                    counts[fp] = counts.get(fp, 0) + 1
        for fp, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            if len(merged) >= TOP:
                break
            if not any(sim(m[1], fp) >= 0.6 for m in merged):
                merged.append([0.01 * n, fp, f"adoption token ×{n}"])
    return [(round(w, 3), short(m), src) for w, m, src in merged[:TOP]]


def predict_direction(corpus, name, run):
    """(session, resemblance, [what it asked after the matching point]) or None."""
    best = None
    for sname, rows in corpus.items():
        if sname == name or len(rows) < 2:
            continue
        fps = [r["fingerprint"] for r in rows]
        # align the session's run against every window of the other session; the window's end is the match point
        for end in range(len(fps)):
            window = fps[max(0, end - len(run) + 1):end + 1]
            score = sum(max(sim(m, w) for w in window) for m in run) / len(run)
            if best is None or score > best[1]:
                best = (sname, score, [short(f) for f in fps[end + 1:end + 4]])
    if best is None or best[1] < MIN_SIM:
        return None
    return best[0], round(best[1], 3), best[2]


def log_path(root, name):
    return os.path.join(sessions_dir(root), name, "mind-reader", "predictions.md")


LOG_HEAD = """# mind-reader — predictions

One entry per prompt of this session: what mind-reader predicted the NEXT owner message would be, and the road the
session seemed to take; the next prompt scores it. Written by the plugin's UserPromptSubmit hook; derived, never a
ruling — an edit here changes no prediction.

```yaml
- after: [the message the prediction was made after]
  time: [YYYY-MM-DD HH:MM]
  next: [weight | predicted message | where it came from] — one line each, at most three
  direction: [the earlier session this one most resembles, its resemblance, what it asked next]
  scored: [filled by the next prompt — the best resemblance of the candidates to the message that arrived]
```

---
"""


def read_log(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def last_entry(log):
    """(the predicted messages of the last unscored entry, its start offset) or (None, None)."""
    body = log.find("\n---\n")                 # the header's own yaml shape is not an entry
    i = log.rfind("\n- after:")
    if i < 0 or i < body:
        return None, None
    entry = log[i:]
    if "\n  scored:" in entry:
        return None, None
    preds = [m.group(1) for m in re.finditer(r"^    - [0-9.]+ \| (.+?) \| [^|]+$", entry, re.M)]
    return preds, i


def running_rate(log):
    scores = [float(m.group(1)) for m in re.finditer(r"^  scored: ([0-9.]+)", log, re.M)]
    if not scores:
        return None
    return len(scores), sum(1 for s in scores if s >= 0.3), round(sum(scores) / len(scores), 3)


def cmd_predict(payload):
    prompt = str(payload.get("prompt") or "").strip()
    root = project_root(payload)
    if not prompt or not os.path.isdir(sessions_dir(root)) or prompt.startswith("<"):
        return 0
    name = session_name(root, str(payload.get("session_id") or ""))
    corpus = load_corpus(root)
    now = os.environ.get("MIND_READER_NOW") or time.strftime("%Y-%m-%d %H:%M")
    path = log_path(root, name)
    log = read_log(path) or LOG_HEAD
    lines = [f"## mind-reader (session {name}) — now: {now}"]
    preds, at = last_entry(log)
    if preds is not None:
        score = round(max((sim(p, prompt) for p in preds), default=0.0), 3)
        log = log.rstrip("\n") + f"\n  scored: {score}\n"
        lines.append(f"- last prediction scored {score} against this message")
    rate = running_rate(log)
    if rate:
        lines.append(f"- running: {rate[1]} of {rate[0]} predictions hit (≥0.3), mean {rate[2]}")
    nxt = predict_next(corpus, name, prompt)
    run = current_run(corpus, name, prompt)
    direction = predict_direction(corpus, name, run)
    if nxt:
        lines.append("- predicted next message:")
        lines += [f"  - {w} — \"{m}\" ({src})" for w, m, src in nxt]
    if direction:
        lines.append(f"- direction: like {direction[0]} (resemblance {direction[1]}), which went on to: "
                     + "; ".join(f'"{d}"' for d in direction[2]) if direction[2] else
                     f"- direction: like {direction[0]} (resemblance {direction[1]}), at its last message")
    lines.append("- a lexical prediction from every session's dispatch record — context for the turn, never an ask; "
                 "the owner's actual words always win")
    entry = [f"\n- after: \"{short(prompt)}\"", f"  time: {now}", "  next:"]
    entry += [f"    - {w} | {m} | {src}" for w, m, src in nxt] or ["    - none"]
    entry.append("  direction: " + (f"{direction[0]} | {direction[1]} | " + " / ".join(direction[2])
                                    if direction else "none"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(log.rstrip("\n") + "\n" + "\n".join(entry) + "\n")
    print("\n".join(lines))
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = payload_from_stdin()
    try:
        if sub == "predict":
            return cmd_predict(payload)
        print(f"mind_reader.py: unknown subcommand {sub!r}")
        return 0
    except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
        print(f"mind-reader ({sub}) degraded: {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
