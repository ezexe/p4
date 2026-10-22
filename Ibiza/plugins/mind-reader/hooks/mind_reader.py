#!/usr/bin/env python3
"""mind_reader.py — the mind-reader plugin: a side agent, detached from the session's conversation, that predicts
what the OWNER will say next — what the owner wants and is thinking, never what the AI wants — and learns from how
each prediction scored.

It is a plain process, not a model: no network, no model call, no tool, nothing written into the conversation. It
reads the p4 vlds dispatch records (the owner's own messages, every session) and the running session's transcript
(only to see how the turn is progressing — what the owner will be reacting to), and writes only its own files and
the gc holds. Its one effect on anything outside itself is the hold: a request that the vlds gc keep an entry the
owner's predicted direction still leans on — retention only, never a deletion, never a steer, expiring on its own.

Subcommands (the hooks run the first three):

  start     (UserPromptSubmit) the owner's message has arrived: the previous turn's FROZEN prediction is scored
            against it, the scored entry appended to the session's vlds partition `mind-reader.md` (a gc-collectable
            object store of the keyspace), the learned per-source weights updated, and a fresh watcher spawned
            detached for this turn. Prints nothing — the session answers uninterrupted.
  watch     (the side agent) re-predicts every few seconds while the transcript grows, rewriting the rotating
            draft `mind-reader/draft.md` (revision n); exits when the next `start` stops it or after IDLE_EXIT of
            silence.
  finalize  (Stop) freezes the prediction from the turn as it ended — the last Stop of a turn wins, so the final
            version is the one standing when the owner's next message arrives — and writes the gc holds.
  status    prints the session's draft, its frozen prediction and the running score, for the owner to track.

Sources, each a learned weight in `.claude/p4/mrindex/model.json`:
  follow     what the owner said after messages resembling this one, any session
  progress   what the owner has said in the state the turn is reaching (files edited and nothing committed →
             the owner's own word for commit; a picker served → its recommended option; a version bumped and no
             reconcile → restart), phrased in the owner's own adoption tokens
  direction  what the owner asked next in the earlier session whose run most resembles this one
  adopt      the owner's most frequent short messages
After a score, each source's weight moves by how well its own best candidate matched the owner's actual message
(a multiplicative-weights step), so the predictor evolves with the owner's history.

Every failure is swallowed into the side agent's log under the notebook's ignored `.out/`; a hook exits 0.
"""

import json
import math
import os
import re
import subprocess
import sys
import time

MIN_SIM = 0.12
TOP = 3
FP_MAX = 160
POLL_S = 3.0
IDLE_EXIT_S = 20 * 60
ETA = 0.8                                   # the learning rate of the weight step
W_MIN, W_MAX = 0.05, 5.0
SOURCES = ("follow", "progress", "direction", "adopt")
HOLD_DAYS = 7
HOLD_MAX = 12
HOLD_FILES = ("local-storage.md", "index.md", "data-store.md", "ledger.md", "logger.md", "virtual.md",
              "session-storage.md", "briefs.md")
PARTITION = "mind-reader.md"
STOP = set("the a an and or to of in on for is it this that be with as at by from are was not but if so do just "
           "what when how which its can all any has have had then than into out up we you i me my your our".split())

PARTITION_HEAD = """# VLDS Partition — Mind-reader

One entry per owner message mind-reader predicted: the prediction frozen when the turn before it ended, and how it scored against what the owner actually said.
Written by the mind-reader plugin's side agent at the owner's next prompt — never by the session, never read by the pool: the side agent stays detached from the conversation.
A gc-collectable partition of the keyspace: the turn-close light pass pours the oldest past the partition's budget into the cold tier, verbatim; nothing here is a ruling, and an edit changes no prediction.
The owner's words are the ground truth; the AI's own intent is never predicted.

```yaml
- predicted: [the top prediction, the owner's likely next message]
  time: [YYYY-MM-DD HH:MM — when the prediction froze]
  after: [the owner message the turn answered]
  next: [weight | message | source — the top three, separated by ' ;; ']
  direction: [the earlier session this one resembled, its resemblance]
  revisions: [how many times the draft rotated before it froze]
  actual: [the owner's next message, as it arrived]
  score: [0..1 — the best resemblance of the three to the actual message]
  sources: [source=score for each source's own best candidate]
```

---
"""


# ---------------------------------------------------------------- text


def tokens(text):
    return {w for w in re.findall(r"[a-z0-9][a-z0-9_.-]*", text.lower()) if len(w) > 2 and w not in STOP}


def sim(a, b):
    ta, tb = (a if isinstance(a, set) else tokens(a)), (b if isinstance(b, set) else tokens(b))
    if not ta or not tb:
        return 1.0 if (isinstance(a, str) and isinstance(b, str) and a.strip().lower() == b.strip().lower()
                       and a.strip()) else 0.0
    return len(ta & tb) / len(ta | tb)


def short(text):
    text = " ".join(str(text).split())
    return text if len(text) <= FP_MAX else text[:FP_MAX - 1] + "…"


def unquote(v):
    v = v.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v


def now_str():
    return os.environ.get("MIND_READER_NOW") or time.strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- places


def payload_from_stdin():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def project_root(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def p4_dir(root):
    return os.path.join(root, ".claude", "p4")


def sessions_dir(root):
    return os.path.join(p4_dir(root), "sessions")


def session_name(root, sid):
    s8 = (sid or "unknown")[:8]
    try:
        return next((n for n in os.listdir(sessions_dir(root)) if n == s8 or n.endswith("--" + s8)), s8)
    except OSError:
        return s8


def work_dir(root, name):
    return os.path.join(sessions_dir(root), name, "mind-reader")


def model_path(root):
    return os.path.join(p4_dir(root), "mrindex", "model.json")


def history_path(root):
    return os.path.join(p4_dir(root), "mrindex", "history.tsv")


def holds_path(root):
    return os.path.join(p4_dir(root), "vindex", "holds.tsv")


def log_file(root, name):
    return os.path.join(p4_dir(root), "scratchpad", ".out", "mind-reader", f"{name}.log")


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def log(root, name, msg):
    try:
        path = log_file(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


# ---------------------------------------------------------------- the owner's corpus


def parse_dispatch(text):
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
            if k in ("time", "arrival"):
                row[k] = v.strip()
    if row:
        rows.append(row)
    return rows


def is_owner(row):
    fp = row.get("fingerprint", "")
    return row.get("arrival", "").startswith("turn") and fp.strip() != "" and not fp.startswith("<")


def load_corpus(root):
    """{session name: [owner messages in time order]}"""
    out = {}
    try:
        names = sorted(os.listdir(sessions_dir(root)))
    except OSError:
        return out
    for name in names:
        path = os.path.join(sessions_dir(root), name, "vlds", "dispatch.md")
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                rows = [r for r in parse_dispatch(f.read()) if is_owner(r)]
        except OSError:
            continue
        rows.sort(key=lambda r: r.get("time", ""))
        if rows:
            out[name] = [r["fingerprint"] for r in rows]
    return out


def stamped(fingerprint, message):
    fp = " ".join(fingerprint.rstrip("…").split()).lower()
    return bool(fp) and " ".join(message.split()).lower().startswith(fp)


def adoption(corpus):
    """[(message, count)] — the owner's short messages, most frequent first."""
    counts = {}
    for msgs in corpus.values():
        for m in msgs:
            k = m.strip().lower()
            if 0 < len(k.split()) <= 3:
                counts[k] = counts.get(k, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def owner_word(adopt, keyword, fallback):
    """The owner's own phrasing for an act: their most frequent short message holding the keyword."""
    return next((m for m, _n in adopt if keyword in m), fallback)


# ---------------------------------------------------------------- the turn's progress (what the owner will react to)


def read_turn(transcript, offset):
    """Signals from the transcript lines appended since `offset` — the turn the owner will react to."""
    sig = {"edited": [], "committed": False, "pushed": False, "bumped": False, "reconciled": False,
           "tested": False, "asked": None, "bytes": 0}
    try:
        with open(transcript, "rb") as f:
            f.seek(offset)
            data = f.read()
    except OSError:
        return sig
    sig["bytes"] = len(data)
    for raw in data.split(b"\n"):
        try:
            rec = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        msg = rec.get("message") if isinstance(rec, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None
        if rec.get("type") != "assistant" or not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            name, inp = item.get("name", ""), item.get("input") or {}
            if name in ("Write", "Edit", "NotebookEdit"):
                fp = str(inp.get("file_path", ""))
                sig["edited"].append(fp)
                if fp.replace("\\", "/").endswith(("plugin.json", "marketplace.json")):
                    sig["bumped"] = True
            elif name in ("Bash", "PowerShell"):
                cmd = str(inp.get("command", ""))
                sig["committed"] |= "git commit" in cmd
                sig["pushed"] |= "git push" in cmd
                sig["reconciled"] |= bool(re.search(r"claude plugin (update|install)", cmd))
                sig["tested"] |= bool(re.search(r"\btest_\w+\.py|pytest|npm test|dotnet test", cmd))
                if re.search(r'"version":\s*"', cmd) and "sed" in cmd:
                    sig["bumped"] = True
            elif name == "AskUserQuestion":
                qs = inp.get("questions") or []
                opts = (qs[0].get("options") or []) if qs and isinstance(qs[0], dict) else []
                labels = [o.get("label", "") for o in opts if isinstance(o, dict)]
                if labels:
                    sig["asked"] = labels
    return sig


def progress_candidates(sig, adopt):
    out = []
    if sig["asked"]:
        rec = next((l for l in sig["asked"] if "recommended" in l.lower()), sig["asked"][0])
        out.append((1.0, re.sub(r"\s*\(recommended\)\s*", "", rec, flags=re.I), "picker served"))
    if sig["edited"] and not sig["committed"]:
        out.append((0.8, owner_word(adopt, "commit", "commit"), "edits, nothing committed"))
    if sig["committed"] and not sig["pushed"]:
        out.append((0.7, owner_word(adopt, "push", "push it"), "committed, not pushed"))
    if sig["bumped"] and not sig["reconciled"]:
        out.append((0.6, owner_word(adopt, "restart", "restart"), "version bumped, not reconciled"))
    if sig["edited"] and not sig["tested"]:
        out.append((0.3, owner_word(adopt, "test", "run the tests"), "edits, nothing tested"))
    return out


# ---------------------------------------------------------------- the predictor


def follow_candidates(corpus, name, message):
    tm = tokens(message)
    out = []
    for sname, msgs in corpus.items():
        for i in range(len(msgs) - 1):
            if sname == name and stamped(msgs[i], message):
                continue
            s = sim(tm, msgs[i])
            if s >= MIN_SIM:
                out.append((s, msgs[i + 1], f"after a like message in {sname}"))
    return out


def direction(corpus, name, run):
    best = None
    for sname, msgs in corpus.items():
        if sname == name or len(msgs) < 2:
            continue
        for end in range(len(msgs)):
            window = msgs[max(0, end - len(run) + 1):end + 1]
            score = sum(max(sim(m, w) for w in window) for m in run) / len(run)
            if best is None or score > best[1]:
                best = (sname, score, msgs[end + 1:end + 3])
    if best is None or best[1] < MIN_SIM:
        return None
    return best[0], round(best[1], 3), best[2]


def predict(corpus, name, message, sig, weights):
    """{'next': [(weight, message, source, why)], 'direction': (...)|None, 'by_source': {source: [messages]}}"""
    adopt = adoption(corpus)
    run = list(corpus.get(name, []))
    if run and stamped(run[-1], message):
        run[-1] = message
    else:
        run.append(message)
    d = direction(corpus, name, run)
    raw = [(s, m, "follow", why) for s, m, why in follow_candidates(corpus, name, message)]
    raw += [(s, m, "progress", why) for s, m, why in progress_candidates(sig, adopt)]
    if d:
        raw += [(d[1], m, "direction", f"what {d[0]} asked next") for m in d[2][:1]]
    total = sum(n for _m, n in adopt) or 1
    raw += [(min(1.0, 3 * n / total), m, "adopt", f"adoption token ×{n}") for m, n in adopt[:TOP]]
    by_source = {}
    for _s, m, src, _w in raw:
        by_source.setdefault(src, []).append(m)
    merged = []
    for s, m, src, why in sorted(raw, key=lambda r: -r[0] * weights.get(r[2], 1.0)):
        w = s * weights.get(src, 1.0)
        for c in merged:
            if sim(c[1], m) >= 0.6:
                c[0] += w
                if src not in c[2].split("+"):
                    c[2] += "+" + src
                break
        else:
            merged.append([w, m, src, why])
    merged.sort(key=lambda c: -c[0])
    return {"next": [(round(w, 3), short(m), src, why) for w, m, src, why in merged[:TOP]],
            "direction": d, "by_source": {k: [short(m) for m in v[:5]] for k, v in by_source.items()}}


def load_weights(root):
    model = read_json(model_path(root), {})
    w = model.get("weights") or {}
    return {s: float(w.get(s, 1.0)) for s in SOURCES}, model


def learn(root, per_source):
    """The multiplicative-weights step: a source whose own best candidate beat the mean gains, one below loses."""
    weights, model = load_weights(root)
    scored = {s: v for s, v in per_source.items() if s in weights}
    if not scored:
        return weights
    mean = sum(scored.values()) / len(scored)
    for s, v in scored.items():
        weights[s] = min(W_MAX, max(W_MIN, weights[s] * math.exp(ETA * (v - mean))))
    norm = sum(weights.values()) / len(weights)
    weights = {s: round(v / norm, 4) for s, v in weights.items()}
    model.update({"weights": weights, "updates": int(model.get("updates", 0)) + 1, "time": now_str()})
    write_atomic(model_path(root), json.dumps(model, indent=2) + "\n")
    return weights


# ---------------------------------------------------------------- the draft and the frozen prediction


def render_draft(name, state, pred, sig, weights, frozen=False):
    lines = [f"# mind-reader — {'FROZEN' if frozen else 'draft'}, session {name}", "",
             f"revision: {state.get('revisions', 0)} · time: {now_str()} · after: \"{short(state.get('message', ''))}\"",
             "", "## The owner's likely next message", ""]
    lines += [f"- {w} — \"{m}\" ({src}: {why})" for w, m, src, why in pred["next"]] or ["- none yet"]
    d = pred["direction"]
    lines += ["", "## Direction", "",
              f"- like {d[0]} (resemblance {d[1]}), which went on to: " + "; ".join(f'"{short(x)}"' for x in d[2])
              if d else "- no earlier session resembles this one yet"]
    lines += ["", "## What the owner will be reacting to", "",
              f"- edited {len(sig['edited'])} file(s); committed: {sig['committed']}; pushed: {sig['pushed']}; "
              f"bumped: {sig['bumped']}; reconciled: {sig['reconciled']}; tested: {sig['tested']}; "
              f"picker: {', '.join(sig['asked']) if sig['asked'] else 'none'}",
              "", "## Learned weights", "", "- " + ", ".join(f"{s} {weights[s]}" for s in SOURCES), ""]
    return "\n".join(lines)


def compute(root, name, state):
    corpus = load_corpus(root)
    sig = read_turn(state.get("transcript", ""), int(state.get("offset", 0)))
    weights, _m = load_weights(root)
    return corpus, sig, weights, predict(corpus, name, state.get("message", ""), sig, weights)


# ---------------------------------------------------------------- the gc holds


def entry_heads(path):
    """[(head value, entry text)] of a hot file's entries."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
    except OSError:
        return []
    try:
        start = lines.index("---") + 1
    except ValueError:
        start = 0
    out, cur = [], None
    for ln in lines[start:]:
        if ln.startswith("- ") and ":" in ln:
            if cur:
                out.append(cur)
            cur = [unquote(ln[2:].split(":", 1)[1]), ln]
        elif cur and ln.startswith("  "):
            cur[1] += " " + ln.strip()
    if cur:
        out.append(cur)
    return [(h, t) for h, t in out]


def hold_key(head):
    return " ".join(head.split())[:32]


def write_holds(root, name, corpus, pred, message):
    """Hold the hot entries the owner's predicted direction leans on, merging every other session's live holds."""
    context = tokens(" ".join([message] + [m for _w, m, _s, _y in pred["next"]] + corpus.get(name, [])[-3:]))
    scored = []
    for sname in sorted(os.listdir(sessions_dir(root))):
        for fname in HOLD_FILES:
            for head, text in entry_heads(os.path.join(sessions_dir(root), sname, "vlds", fname)):
                te = tokens(text)
                shared = len(te & context)
                if shared >= 3 and len(te) >= 3:
                    scored.append((shared / min(len(te), len(context)), sname, fname, head))
    scored.sort(key=lambda r: -r[0])
    expires = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + HOLD_DAYS * 86400))
    if os.environ.get("MIND_READER_NOW"):
        expires = "9999-12-31 00:00"
    rows = []
    try:
        with open(holds_path(root), encoding="utf-8") as f:
            for ln in f:
                parts = ln.rstrip("\n").split("\t")
                if ln.startswith("#") or len(parts) < 6 or parts[1] == name or parts[0] < now_str():
                    continue
                rows.append(ln.rstrip("\n"))
    except OSError:
        pass
    seen = set()
    for score, sname, fname, head in scored:
        k = (sname, fname, hold_key(head))
        if k in seen:
            continue
        seen.add(k)
        rows.append("\t".join([expires, name, f"{sname}/{fname}", hold_key(head).replace("\t", " "), f"{score:.2f}",
                               "the owner's predicted direction leans on it"]))
        if len(seen) >= HOLD_MAX:
            break
    head = ("# vindex holds — expires\tsession\tstore/file\thead (first 32 chars)\tscore\treason — written by the "
            "mind-reader side agent; the vlds light pass and judged sweep never pour a held entry before it expires "
            "(the owner's archive ignores holds); retention only, never a deletion\n")
    write_atomic(holds_path(root), head + "".join(r + "\n" for r in rows))
    return len(seen)


# ---------------------------------------------------------------- the commands


def state_path(root, name):
    return os.path.join(work_dir(root, name), "state.json")


def spawn_watcher(root, name):
    args = [sys.executable, os.path.abspath(__file__), "watch", "--root", root, "--name", name]
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
          "close_fds": True, "cwd": root}
    if os.name == "nt":
        base = 0x00000200 | 0x08000000           # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        for flags in (base | 0x01000000, base):  # try CREATE_BREAKAWAY_FROM_JOB first: outlive the hook's job
            try:
                return subprocess.Popen(args, creationflags=flags, **kw).pid
            except OSError:
                continue
        return None
    return subprocess.Popen(args, start_new_session=True, **kw).pid


def score_frozen(root, name, message):
    """Score the turn's frozen prediction against the owner's message; append it to the vlds partition; learn."""
    wd = work_dir(root, name)
    frozen = read_json(os.path.join(wd, "frozen.json"), None)
    if not frozen or frozen.get("scored"):
        return None
    nxt = frozen["pred"]["next"]
    score = round(max((sim(m, message) for _w, m, _s, _y in nxt), default=0.0), 3)
    per = {s: round(max((sim(m, message) for m in frozen["pred"]["by_source"].get(s, [])), default=0.0), 3)
           for s in SOURCES if frozen["pred"]["by_source"].get(s)}
    weights = learn(root, per)
    d = frozen["pred"].get("direction")
    store = os.path.join(sessions_dir(root), name, "vlds")
    part = os.path.join(store, PARTITION)
    lock = os.path.join(store, "idb", ".sweep-lock")      # vlds idb.py's LOCK
    for _ in range(25):                          # the idb light pass may be trimming the partition: wait it out
        if not os.path.exists(lock):
            break
        time.sleep(0.2)
    entry = [f"- predicted: \"{short(nxt[0][1]) if nxt else 'none'}\"", f"  time: {frozen['time']}",
             f"  after: \"{short(frozen['message'])}\"",
             "  next: " + " ;; ".join(f"{w} | {m} | {s}" for w, m, s, _y in nxt),
             f"  direction: {d[0]} | {d[1]}" if d else "  direction: none",
             f"  revisions: {frozen.get('revisions', 0)}", f"  actual: \"{short(message)}\"", f"  score: {score}",
             "  sources: " + ", ".join(f"{s}={v}" for s, v in per.items())]
    try:
        with open(part, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = PARTITION_HEAD
    os.makedirs(store, exist_ok=True)
    with open(part, "w", encoding="utf-8", newline="\n") as f:
        f.write(text.rstrip("\n") + "\n\n" + "\n".join(entry) + "\n")
    os.makedirs(os.path.dirname(history_path(root)), exist_ok=True)
    new = not os.path.exists(history_path(root))
    with open(history_path(root), "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write("# mind-reader history — time\tsession\tscore\t" + "\t".join(SOURCES) + "\n")
        f.write("\t".join([now_str(), name, str(score)] + [str(per.get(s, "")) for s in SOURCES]) + "\n")
    frozen["scored"] = score
    write_atomic(os.path.join(wd, "frozen.json"), json.dumps(frozen, indent=1) + "\n")
    return score, weights


def cmd_start(payload):
    root = project_root(payload)
    message = str(payload.get("prompt") or "").strip()
    if not os.path.isdir(sessions_dir(root)) or not message or message.startswith("<"):
        return 0                                  # an agent message or task notification is not the owner's
    name = session_name(root, str(payload.get("session_id") or ""))
    wd = work_dir(root, name)
    os.makedirs(wd, exist_ok=True)
    write_atomic(os.path.join(wd, "stop"), now_str() + "\n")        # the last turn's watcher ends
    try:
        r = score_frozen(root, name, message)
        if r:
            log(root, name, f"scored {r[0]} against the owner's message; weights {r[1]}")
    except Exception as e:  # noqa: BLE001
        log(root, name, f"score failed: {type(e).__name__}: {e}")
    tp = str(payload.get("transcript_path") or "")
    try:
        offset = os.path.getsize(tp) if tp else 0
    except OSError:
        offset = 0
    state = {"message": message, "transcript": tp, "offset": offset, "revisions": 0, "time": now_str()}
    write_atomic(state_path(root, name), json.dumps(state, indent=1) + "\n")
    os.remove(os.path.join(wd, "stop"))
    if os.environ.get("MIND_READER_NO_SPAWN"):
        return 0
    pid = spawn_watcher(root, name)
    log(root, name, f"watcher spawned pid={pid}")
    return 0


def cmd_watch(root, name):
    wd = work_dir(root, name)
    last_size, idle_since = -1, time.time()
    while True:
        if os.path.exists(os.path.join(wd, "stop")):
            return 0
        state = read_json(state_path(root, name), None)
        if not state:
            return 0
        try:
            size = os.path.getsize(state["transcript"]) if state.get("transcript") else 0
        except OSError:
            size = 0
        if size != last_size:
            idle_since, last_size = time.time(), size
            try:
                corpus, sig, weights, pred = compute(root, name, state)
                state["revisions"] = int(state.get("revisions", 0)) + 1
                write_atomic(state_path(root, name), json.dumps(state, indent=1) + "\n")
                write_atomic(os.path.join(wd, "draft.md"), render_draft(name, state, pred, sig, weights))
            except Exception as e:  # noqa: BLE001
                log(root, name, f"revision failed: {type(e).__name__}: {e}")
        elif time.time() - idle_since > IDLE_EXIT_S:
            return 0
        if os.environ.get("MIND_READER_ONCE"):
            return 0
        time.sleep(POLL_S)


def cmd_finalize(payload):
    root = project_root(payload)
    if not os.path.isdir(sessions_dir(root)):
        return 0
    name = session_name(root, str(payload.get("session_id") or ""))
    state = read_json(state_path(root, name), None)
    if not state:
        return 0
    corpus, sig, weights, pred = compute(root, name, state)
    wd = work_dir(root, name)
    frozen = {"time": now_str(), "message": state["message"], "revisions": state.get("revisions", 0), "pred": pred}
    write_atomic(os.path.join(wd, "frozen.json"), json.dumps(frozen, indent=1) + "\n")
    write_atomic(os.path.join(wd, "draft.md"), render_draft(name, state, pred, sig, weights, frozen=True))
    n = write_holds(root, name, corpus, pred, state["message"])
    log(root, name, f"froze revision {state.get('revisions', 0)}; {n} hold(s) written")
    return 0


def cmd_status(payload):
    root = project_root(payload)
    name = session_name(root, str(payload.get("session_id") or os.environ.get("MIND_READER_SESSION", "")))
    for f in ("draft.md",):
        path = os.path.join(work_dir(root, name), f)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                print(fh.read())
    try:
        with open(history_path(root), encoding="utf-8") as f:
            rows = [ln.split("\t") for ln in f if not ln.startswith("#")]
        scores = [float(r[2]) for r in rows if len(r) > 2]
        if scores:
            print(f"history: {len(scores)} scored, {sum(1 for s in scores if s >= 0.3)} hit (>=0.3), "
                  f"mean {sum(scores) / len(scores):.3f}; last 5: {', '.join(r[2] for r in rows[-5:])}")
    except OSError:
        pass
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if sub == "watch":
            a = sys.argv[2:]
            return cmd_watch(a[a.index("--root") + 1], a[a.index("--name") + 1])
        payload = payload_from_stdin()
        if sub == "start":
            return cmd_start(payload)
        if sub == "finalize":
            return cmd_finalize(payload)
        if sub == "status":
            return cmd_status(payload)
        return 0
    except Exception:  # noqa: BLE001 — a side agent never disturbs the session it watches
        return 0


if __name__ == "__main__":
    sys.exit(main())
