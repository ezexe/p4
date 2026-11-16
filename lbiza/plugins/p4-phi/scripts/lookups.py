#!/usr/bin/env python3
"""lookups.py: what every tool call found, kept, and checked before the next call like it runs.

A session starts knowing nothing of what earlier sessions looked up or ran into, so it looks the same page up again
and walks into the same failing command. This module records the tool calls hook.py hands it after they ran, from
the PostToolUse and PostToolUseFailure hooks, and checks a call before it runs, from the PreToolUse hook:

  record   one row per tool_use id in phi/models/lookups.db, this machine's sqlite database, which the store's
           .gitignore leaves out: the tool, the call's question and target, whether it worked, the error's
           signature when it did not, and what it found, which is a web call's answer, a subagent's report or a
           failure's last lines. A command that works within a few calls after a failed one like it, in the same
           session or subagent, becomes that failure's `fix`. Web findings and fixed failures are also appended to
           phi/store/lookups.jsonl, which git tracks and `p4.py sync` merges, so a database made on another machine
           starts with them.
  after    a call that fails with a signature other sessions already met is told so beside its result, with the
           command that worked next there, as the additionalContext of its PostToolUse or PostToolUseFailure hook.
           This is exact: the error has happened.
  check    before a WebFetch, the earlier findings for the same page read from the same `offset` are scored against
           the new question, and before a WebSearch those of every earlier search with the same `mode`,
           `allowed_domains` and `blocked_domains`, leaving out a finding older than `max_age_days`; the
           findings that reach the threshold, the best first and at most `SHOWN_ROWS`, are the answer. Before a
           shell command, the failure model scores it, and for a command it expects to fail the answer is the
           nearest earlier failure of the same program and its fix, if any. A call of any other tool that reaches
           `check` is logged and never stopped. hooks/recall-hook.sh ends the check of most calls before python
           starts, so they leave no row, and runs a clean call's record in a python the call does not wait for.
  train    `lookups.py train`, run by hand, measures the matcher, an idf-weighted cosine of the two questions,
           against a fitted model on calls held out by session, with the labels the history gives for free: a
           pair is positive when the later call's own result is like the earlier finding. The failure model is
           fitted on the earlier commands and tested on the later ones. The weights a round keeps are then fitted
           again on all the calls, held-out ones too. A round writes phi/models/lookups-model.json whenever the
           matcher or either model finds a threshold at `recall.lookups.min_precision`. The file always holds the
           web model's weights, and a check uses them in place of the matcher only when the round marked them
           `promoted`, for answering more held-out calls than the matcher; it holds the failure model's weights
           only when that model found a threshold. Every round appends its figures to phi/models/lookups-eval.tsv.

The mode of a web call is p4.json's `recall.lookups.web`, and that of a shell command `recall.lookups.shell`:
"answer" hands the answer back in place of the call as the reason of a PreToolUse deny, once, so the same call
made again by the same session or subagent runs; "note" puts the answer beside the result and lets the call run;
"shadow" only logs it; "off" does not look. `recall.lookups.on` false turns recording and checking off, and
`recall.lookups.after` false turns off only what a failure is told after it.

A check goes by likeness and not by key, since the same command seldom runs twice: a key would answer almost
nothing. A subagent's brief and report are kept as a row and never served: many briefs fill one template with
different inputs, so a brief like an earlier one seldom gets a like report.
"""

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import ranker  # noqa: E402

DB = "lookups.db"
KEPT = "lookups.jsonl"           # phi/store/lookups.jsonl: web findings and fixed failures, which git tracks
MODEL = "lookups-model.json"
EVAL = "lookups-eval.tsv"
MODEL_KIND = "p4 lookups model"
ON = True
WEB = "answer"
SHELL = "shadow"                 # logged only: a failure foreseen from a command's words is too often wrong to stop it
AFTER = True                     # tell a failed call what earlier sessions did about the same error
THRESHOLD = None                 # None: the threshold a training round set for the road in use, else FALLBACK
FALLBACK = 0.6
MIN_PRECISION = 0.85
MAX_AGE_DAYS = 30
FINDING_CHARS = 4000
SHOWN_CHARS = 1500
SHOWN_ROWS = 2                   # earlier findings shown for one web call
LABEL_COS = 0.35                 # a later result this like an earlier finding: the finding would have answered.
#                                  A small model writes each answer, so one question asked twice of one page gets
#                                  results about half alike at the median, and unrelated pages hardly alike at all;
#                                  0.35 keeps about seven in ten of the true repeats and none of the unrelated pairs
FIX_LOOK = 6                     # a failure is fixed by a like command that works among the next few calls of its
#                                  session or subagent
FIX_COS = 0.35
EPOCHS_WEB = 30                  # the web model's rounds, ten full-batch steps each: longer training fits the pairs
#                                  better and answers no more held-out calls
EPOCHS_SHELL = 6                 # the failure model's passes: more passes learn the earlier commands by heart and
#                                  foresee the later ones no better

SHELL_TOOLS = ("Bash", "PowerShell")
# "NotebookRead", "MultiEdit" and "Task" are tool names of older Claude Code versions, still met in their transcripts
KINDS = {"WebFetch": "web", "WebSearch": "web", "Bash": "shell", "PowerShell": "shell", "Read": "read",
         "NotebookRead": "read", "Grep": "search", "Glob": "search", "Edit": "edit", "Write": "edit",
         "MultiEdit": "edit", "NotebookEdit": "edit", "Agent": "agent", "Task": "agent"}
WS = re.compile(r"\s+")
STRONG = re.compile(r"(^\s*[\w.]*(Error|Exception)\b\s*[:(]|command not found|is not recognized as|"
                    r"No such file or directory|unexpected EOF|^\s*fatal: |Permission denied|ENAMETOOLONG|"
                    r"unterminated string|cannot access|CommandNotFoundException|ParserError)")
# one leading blank a line, never `[ \t]+.*`: the two would share a line's indentation in as many ways as it has
# blanks, and a long indented block with no error line after it then takes the pattern forever to give up
TRACEBACK = re.compile(r"Traceback \(most recent call last\):\n(?:[ \t].*\n)+([\w.]*(?:Error|Exception|Exit|Interrupt)\b.*)")
NUM = re.compile(r"0x[0-9a-fA-F]+|\b\d+\b")
PATH = re.compile(r"(?:[A-Za-z]:)?[\\/][\w .\\/~+-]*[\\/]")
HEX = re.compile(r"\b[0-9a-f]{7,}\b")
LEAD = re.compile(r"^(?:cd\s+(?:\"[^\"]*\"|'[^']*'|\S+)\s*(?:&&|;)\s*|[A-Za-z_]\w*=(?:\"[^\"]*\"|'[^']*'|\S*)\s*;?\s*)+")
SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, time TEXT, session TEXT, agent TEXT, tool TEXT, kind TEXT,
  key TEXT, target TEXT, ask TEXT, ok INTEGER, sig TEXT, finding TEXT, fix TEXT);
CREATE INDEX IF NOT EXISTS calls_key ON calls (key);
CREATE INDEX IF NOT EXISTS calls_sig ON calls (sig) WHERE sig != '';
CREATE INDEX IF NOT EXISTS calls_target ON calls (kind, target);
CREATE INDEX IF NOT EXISTS calls_agent ON calls (session, agent);
CREATE TABLE IF NOT EXISTS checks (time TEXT, session TEXT, agent TEXT, tool TEXT, key TEXT, action TEXT,
  score REAL, shown TEXT);
CREATE TABLE IF NOT EXISTS pending (session TEXT, agent TEXT, key TEXT, time TEXT, PRIMARY KEY (session, agent, key));
"""


def configure(p4):
    import p4conf
    p4conf.configure(globals(), p4, "recall.lookups", {
        "on": "ON", "web": "WEB", "shell": "SHELL", "after": "AFTER", "threshold": "THRESHOLD",
        "min_precision": "MIN_PRECISION", "max_age_days": "MAX_AGE_DAYS", "finding_chars": "FINDING_CHARS",
        "shown_chars": "SHOWN_CHARS", "epochs_web": "EPOCHS_WEB", "epochs_shell": "EPOCHS_SHELL"}, write=False)


# --- a call's kind, key, question and target ----------------------------------------------------------------

def kind(tool):
    return KINDS.get(tool, "other")


def norm_url(u):
    return re.sub(r"[#?].*$", "", (u or "").strip().lower()).rstrip("/")


def norm_path(p):
    return (p or "").replace("\\", "/").lower()


def program(cmd):
    """The first program a command runs, past any `cd x &&` and VAR=value prefixes: python, git, cmake."""
    m = re.match(r"[\"']?([\w.+-]+(?:[\\/][\w.+-]+)*)", LEAD.sub("", cmd.strip()))
    return os.path.basename(m.group(1).replace("\\", "/")).lower() if m else ""


def ask_of(tool, inp):
    """The text a call asks with: a command, a fetch's prompt, a search's query, a pattern, a path, or a subagent's
    type and brief."""
    g = lambda k: str(inp.get(k) or "")  # noqa: E731
    if tool in SHELL_TOOLS:
        return WS.sub(" ", g("command")).strip()
    if tool == "WebFetch":
        return WS.sub(" ", g("prompt")).strip()
    if tool == "WebSearch":
        return WS.sub(" ", g("query")).strip()
    if tool in ("Grep", "Glob"):
        return " ".join(x for x in (g("pattern"), g("path"), g("glob"), g("type"), g("output_mode")) if x)
    if tool in ("Read", "NotebookRead", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        return " ".join(x for x in (g("file_path") or g("notebook_path"), g("offset"), g("limit")) if x)
    if tool in ("Agent", "Task"):
        return WS.sub(" ", g("subagent_type") + " " + g("prompt")).strip()
    try:
        return json.dumps(inp, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(inp)


TARGET_CHARS = 400               # a target as the table keeps it: a longer one is cut and its whole hash appended


def target_of(tool, inp):
    """What a call is about, exactly: a page and the character a fetch starts reading it at, a search's domains and
    mode, a file, a program. Calls about the same target are the candidates. One longer than TARGET_CHARS is its
    start and a hash of the whole, so it fits the table and stays apart from another that starts the same."""
    if tool == "WebFetch":
        try:
            at = int(inp.get("offset") or 0)
        except (TypeError, ValueError):
            at = 0
        t = norm_url(inp.get("url")) + (f"#offset={at}" if at > 0 else "")
    elif tool == "WebSearch":
        t = "search" + search_scope(inp)
    elif tool in SHELL_TOOLS:
        t = program(str(inp.get("command") or ""))
    else:
        t = norm_path(str(inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""))
    if len(t) <= TARGET_CHARS:
        return t
    return t[:TARGET_CHARS - 17] + "~" + hashlib.sha1(t.encode("utf-8", "replace")).hexdigest()[:16]


def search_scope(inp):
    """A search's mode and domains as the end of its target: '' for a standard search of every domain, else
    `?mode=extended&allowed=a.org,b.org&blocked=c.org` with the parts it has, each domain list lower-cased and
    sorted."""
    parts = []
    mode = str(inp.get("mode") or "").strip().lower()
    if mode and mode != "standard":
        parts.append("mode=" + mode)
    for k in ("allowed", "blocked"):
        v = inp.get(k + "_domains")
        v = [v] if isinstance(v, str) else v if isinstance(v, list) else []
        doms = sorted({str(d).strip().lower() for d in v if str(d).strip()})
        if doms:
            parts.append(k + "=" + ",".join(doms))
    return "?" + "&".join(parts) if parts else ""


def key_of(tool, inp):
    """Two calls with one key are the same call: the tool, its target and its question, with spacing set aside, and
    case too except in a command. An Edit or a Write adds a hash of the text it replaces or writes."""
    ask = ask_of(tool, inp)
    if tool in ("Edit", "Write", "MultiEdit"):
        ask += "|" + hashlib.sha1(str(inp.get("old_string") or inp.get("content") or "").encode("utf-8", "replace")
                                  ).hexdigest()[:8]
    base = f"{tool}|{target_of(tool, inp)}|{ask if tool in SHELL_TOOLS else ask.lower()}"
    return hashlib.sha1(base.encode("utf-8", "replace")).hexdigest()[:16]


def flatten(resp, limit=200000):
    """A tool's response as text: a string as it is, every string inside an object or list otherwise."""
    if isinstance(resp, str):
        return resp[:limit]
    out = []

    def walk(v):
        if isinstance(v, str):
            if v.strip():
                out.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
    walk(resp)
    return "\n".join(out)[:limit]


def signature(text, failed):
    """An error's signature: its telling line with the paths, numbers and hashes taken out, so the same mistake reads
    the same in another directory or on another line. A call not marked failed has one only when its last lines
    are an unmistakable error or a Python traceback stands anywhere in it, as when a command piped through `tail`
    or followed by `; other-command` exits 0 with the traceback mid-output; source code that mentions an error has
    none. A failed call with no telling line and no traceback has no signature: its last line is whatever it
    printed, and two unrelated failures must not read as one."""
    text = (text or "").replace("\r", "")              # Windows output ends its lines \r\n
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    pick = ""
    for l in reversed(lines[-12:] if failed else lines[-3:]):
        if STRONG.search(l):
            pick = l
            break
    if not pick:
        m = TRACEBACK.search(text or "")
        if not m:
            return ""
        pick = m.group(1)
    pick = HEX.sub("<hex>", PATH.sub("<dir>/", pick.strip()))
    return WS.sub(" ", NUM.sub("N", pick))[:160]


# --- the database -------------------------------------------------------------------------------------------

def db_path(p4):
    return p4conf.sub(p4, "models", DB)


def kept_path(p4):
    return p4conf.sub(p4, "store", KEPT)


def model_path(p4):
    return p4conf.sub(p4, "models", MODEL)


def connect(p4):
    """The database, made when missing and then filled from phi/store/lookups.jsonl, which another machine may have
    written. A file that is not a database is set aside as lookups.db.bad: a call is never failed over it."""
    path = db_path(p4)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    if new:
        # made under another name with its tables, then moved in whole: another process never finds the file
        # without them; when two make it at once, the first move wins and the other's copy is dropped
        tmp = f"{path}.new-{os.getpid()}"
        try:
            made = sqlite3.connect(tmp)
            made.executescript(SCHEMA)
            made.close()
            if not os.path.exists(path):
                os.replace(tmp, path)
        except (OSError, sqlite3.DatabaseError):
            pass
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    for attempt in (0, 1):
        con = sqlite3.connect(path, timeout=3.0)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.executescript(SCHEMA)
            break
        except sqlite3.DatabaseError:
            con.close()
            if attempt:
                raise
            for ext in ("", "-wal", "-shm"):
                try:
                    os.replace(path + ext, path + ".bad" + ext)
                except OSError:
                    pass
            new = True
    con.row_factory = sqlite3.Row
    if new and os.path.exists(kept_path(p4)):
        import_kept(p4, con)
    return con


def import_kept(p4, con):
    n = 0
    try:
        f = open(kept_path(p4), encoding="utf-8")
    except OSError:
        return 0
    with f:
        for line in f:
            try:
                r = json.loads(line)
                cols = ("id", "time", "session", "agent", "tool", "kind", "key", "target", "ask", "ok", "sig",
                        "finding", "fix")
                cur = con.execute("INSERT OR IGNORE INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                  [r.get(c, "") if c != "ok" else int(bool(r.get("ok"))) for c in cols])
                n += cur.rowcount
            except (ValueError, TypeError, sqlite3.Error):
                continue
    con.commit()
    return n


def keep(p4, row):
    """Append a row to the tracked file: a finding or a fixed failure, the knowledge worth another machine's having."""
    path = kept_path(p4)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def cos(a, b, idf):
    """idf-weighted cosine of two token lists."""
    ta, tb = {}, {}
    for t in a:
        ta[t] = ta.get(t, 0) + 1
    for t in b:
        tb[t] = tb.get(t, 0) + 1
    num = sum(v * tb[t] * idf(t) ** 2 for t, v in ta.items() if t in tb)
    da = math.sqrt(sum((v * idf(t)) ** 2 for t, v in ta.items()))
    db_ = math.sqrt(sum((v * idf(t)) ** 2 for t, v in tb.items()))
    return num / (da * db_) if da and db_ else 0.0


def flat_idf(_t):
    return 1.0


def insert(con, d, p4=None):
    """One call into the table, once per id: d is {id, time, session, agent, tool, inp, ok, text}. Returns the row
    written, or None when the id is already there. A working shell command also becomes the fix of the latest like
    failed command among the few calls before it in the same session or subagent. With `p4`, a web finding and a
    fixed failure are also appended to the tracked file."""
    tool, inp = d["tool"], d.get("inp") if isinstance(d.get("inp"), dict) else {}
    k = kind(tool)
    text = d.get("text") or ""
    failed = d.get("ok") is False
    sig = signature(text, failed) if (failed or k == "shell") else ""
    ok = 0 if (failed or sig) else 1
    if ok and k == "web":
        finding = text[:FINDING_CHARS]
    elif ok and k == "agent":
        finding = text[:FINDING_CHARS // 2]
    elif not ok:
        finding = text[-600:]
    else:
        finding = ""
    row = {"id": d["id"], "time": d.get("time") or "", "session": d.get("session") or "", "agent": d.get("agent") or "",
           "tool": tool, "kind": k, "key": key_of(tool, inp), "target": target_of(tool, inp),
           "ask": ask_of(tool, inp)[:2000], "ok": ok, "sig": sig, "finding": finding, "fix": ""}
    cur = con.execute("INSERT OR IGNORE INTO calls VALUES (:id,:time,:session,:agent,:tool,:kind,:key,:target,:ask,"
                      ":ok,:sig,:finding,:fix)", row)
    if not cur.rowcount:
        return None
    if ok and k == "shell":
        mine = ranker.tokens(row["ask"])
        for r in con.execute("SELECT rowid, * FROM calls WHERE session=? AND agent=? AND id!=? ORDER BY rowid DESC "
                             "LIMIT ?", (row["session"], row["agent"], row["id"], FIX_LOOK)).fetchall():
            if r["ok"] == 0 and r["kind"] == "shell" and not r["fix"] and r["ask"] != row["ask"] \
                    and cos(mine, ranker.tokens(r["ask"]), flat_idf) >= FIX_COS:
                con.execute("UPDATE calls SET fix=? WHERE rowid=?", (row["ask"][:600], r["rowid"]))
                if p4:
                    keep(p4, {**{c: r[c] for c in r.keys() if c != "rowid"}, "fix": row["ask"][:600]})
                break
    if p4 and ok and k == "web" and len(finding) >= 80:
        keep(p4, row)
    return row


# --- record: PostToolUse and PostToolUseFailure -------------------------------------------------------------

def record(p4, payload, when):
    """Write the call's row; return the text for a failure other sessions already hit, or ''."""
    configure(p4)
    if not ON:
        return ""
    tool = payload.get("tool_name") or ""
    tid = payload.get("tool_use_id") or ""
    if not tool or not tid:
        return ""
    failure = payload.get("hook_event_name") == "PostToolUseFailure"
    resp = payload.get("error") if failure else payload.get("tool_response", payload.get("tool_result"))
    text = flatten(resp if resp is not None else "")
    session = payload.get("session_id") or ""
    con = connect(p4)
    try:
        row = insert(con, {"id": tid, "time": when, "session": session, "agent": payload.get("agent_id") or "",
                           "tool": tool, "inp": payload.get("tool_input"), "ok": not failure, "text": text}, p4)
        con.commit()
        if not row or row["ok"] or not row["sig"] or not AFTER:
            return ""
        return after_text(con, row)
    finally:
        con.close()


def after_text(con, row):
    """What earlier sessions did about this error, or '' when none of them met it, or when this session or subagent
    was told already: each telling is a row of `checks` with the action `after` and the signature as `shown`."""
    if con.execute("SELECT 1 FROM checks WHERE session=? AND agent=? AND action='after' AND shown=?",
                   (row["session"], row["agent"], row["sig"])).fetchone():
        return ""
    seen = con.execute("SELECT session, time, ask, fix FROM calls WHERE sig=? AND session!=? ORDER BY rowid DESC "
                       "LIMIT 200", (row["sig"], row["session"])).fetchall()
    if not seen:
        return ""
    con.execute("INSERT INTO checks VALUES (?,?,?,?,?,?,?,?)", (row["time"], row["session"], row["agent"], row["tool"],
                                                               row["key"], "after", 0.0, row["sig"]))
    con.commit()
    sessions = len({r["session"] for r in seen})
    out = (f"phi (p4-phi): this error was met before, in {sessions} earlier session{'s' if sessions != 1 else ''}, "
           f"last at {seen[0]['time']}: {row['sig']}")
    fixed = [r for r in seen if r["fix"]]
    if fixed:
        out += f"\nThere the failed command was: {fixed[0]['ask'][:300]}\nand what ran next and worked: {fixed[0]['fix'][:400]}"
    return out


# --- check: PreToolUse --------------------------------------------------------------------------------------

def load_model(p4):
    try:
        with open(model_path(p4), encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m, dict) and m.get("kind") == MODEL_KIND else None
    except (OSError, ValueError):
        return None


def web_rows(con):
    return con.execute("SELECT id, time, session, tool, target, ask, finding FROM calls WHERE kind='web' AND ok=1 "
                       "AND finding!='' ORDER BY time, rowid").fetchall()


def idf_from(token_lists):
    n = len(token_lists)
    df = {}
    for ts in token_lists:
        for t in set(ts):
            df[t] = df.get(t, 0) + 1
    return lambda t: math.log(1 + n / (1 + df.get(t, 0)))


def pair_features(new_toks, new_tool, old_toks, old_find_toks, days, idf):
    """How an earlier web row stands to a new question: the model's inputs."""
    mine = set(new_toks)
    total = sum(idf(t) for t in mine) or 1.0
    theirs, found = set(old_toks), set(old_find_toks)
    c = cos(new_toks, old_toks, idf)
    return {"bias": 1.0, "cos": c, "cos2": c * c,
            "cover": sum(idf(t) for t in mine if t in theirs) / total,
            "found": sum(idf(t) for t in mine if t in found) / total,
            "same": 1.0 if mine == theirs else 0.0,
            "short": 1.0 if len(mine) < 4 else 0.0,
            "search": 1.0 if new_tool == "WebSearch" else 0.0,
            "age": math.log1p(days or 0.0) / 5.0}


def lin(w, x):
    z = sum(w.get(k, 0.0) * v for k, v in x.items())
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def web_candidates(rows, tool, target):
    """The earlier calls a web call is scored against: those of the same tool and target, which is for a fetch the
    page and the character it starts reading at, and for a search its mode and domains."""
    return [r for r in rows if r["tool"] == tool and r["target"] == target]


def web_match(con, p4, tool, inp, when):
    """`(score, row, threshold)` of the best earlier finding for this web call, or `(0.0, None, threshold)` when
    there is none to compare. The runners-up that reach the threshold are left on `web_match.also`."""
    model = load_model(p4) or {}
    web = model.get("web") or {}
    use_model = bool(web.get("w")) and web.get("promoted")
    thr = THRESHOLD if THRESHOLD is not None else web.get("threshold" if use_model else "matcher_threshold")
    thr = FALLBACK if thr is None else thr
    rows = web_rows(con)
    target, ask = target_of(tool, inp), ranker.tokens(ask_of(tool, inp))
    cands = web_candidates(rows, tool, target)
    web_match.also = []
    if not cands or not ask:
        return 0.0, None, thr
    idf = idf_from([ranker.tokens(r["ask"]) for r in rows])
    best, best_row, passed = 0.0, None, []
    for r in cands:
        days = ranker.days_between(r["time"], when)
        if days is not None and days > MAX_AGE_DAYS:
            continue
        old = ranker.tokens(r["ask"])
        if use_model:
            s = lin(web["w"], pair_features(ask, tool, old, ranker.tokens(r["finding"]), days, idf))
        else:
            s = cos(ask, old, idf)
        if s >= thr:
            passed.append((s, r))
        if s >= best:                          # the newest of equals
            best, best_row = s, r
    # a page asked the same thing more than once, as when a first answer fell short: the runners-up are shown too,
    # up to SHOWN_ROWS findings, since the best match by the question is not always the fullest answer
    web_match.also = [r for _, r in sorted(passed, key=lambda t: -t[0]) if r is not best_row][:SHOWN_ROWS - 1]
    return best, best_row, thr


def shell_features(cmd, tool):
    """A command as the failure model reads it: its words, the programs it runs, and a few shapes that fail."""
    x = {}
    for t in set(ranker.tokens(cmd)):
        x[ranker.h("t:" + t)] = 1.0
    for seg in re.split(r"&&|\|\||[|;\n]", cmd):
        p = program(seg)
        if p:
            x[ranker.h("p:" + p)] = 1.0
    here = "<<" in cmd
    flags = {"heredoc": here, "heredoc-quote": here and cmd.count("'") % 2 == 1, "backtick": cmd.count("`") % 2 == 1,
             "sleep": bool(re.search(r"\bsleep\s+\d|Start-Sleep", cmd)), "inline-py": " -c " in cmd and "python" in cmd,
             "long": len(cmd) > 2000, "ps": tool == "PowerShell", "nonascii": any(ord(c) > 127 for c in cmd)}
    for k, v in flags.items():
        if v:
            x[ranker.h("f:" + k)] = 1.0
    x[ranker.h("bias")] = 1.0
    return x


def shell_match(con, p4, tool, inp):
    """`(score, row, threshold)` for a shell command: the failure model's score and, when it reaches the threshold,
    the nearest earlier failure of the same program, one with a fix ahead by a little. `(0.0, None, None)` while the
    store has no failure model."""
    model = (load_model(p4) or {}).get("shell") or {}
    if not model.get("w") or model.get("threshold") is None:
        return 0.0, None, None
    cmd = ask_of(tool, inp)
    w = {int(k): v for k, v in model["w"].items()}
    s = ranker.score(w, shell_features(cmd, tool))
    if s < model["threshold"]:
        return s, None, model["threshold"]
    mine = ranker.tokens(cmd)
    best, best_row = 0.0, None
    for r in con.execute("SELECT session, time, ask, sig, fix FROM calls WHERE kind='shell' AND ok=0 AND target=? "
                         "ORDER BY rowid DESC LIMIT 300", (target_of(tool, inp),)).fetchall():
        c = cos(mine, ranker.tokens(r["ask"]), flat_idf) + (0.05 if r["fix"] else 0.0)
        if c > best:
            best, best_row = c, r
    return s, best_row, model["threshold"]


def web_text(row):
    if row["tool"] == "WebFetch":
        what = (f"a page lookup, WebFetch {row['target']}, at {row['time']}. A small model wrote the answer from the "
                f"page, so it is a reading of the page and not the page itself.")
    else:
        what = f"a web search, at {row['time']}. What it found is what the search returned then."
    return (f"phi (p4-phi): this was looked up before, {what}\n"
            f"Asked then: {row['ask'][:300]}\nFound then: {row['finding'][:SHOWN_CHARS]}")


def shell_text(row):
    out = (f"phi (p4-phi): a command like this failed before, at {row['time']}: {row['sig']}\n"
           f"It was: {row['ask'][:300]}")
    if row["fix"]:
        out += f"\nWhat ran next and worked: {row['fix'][:400]}"
    return out


AGAIN = "\nIf that answers it, use it. Make the same call again unchanged to run it anyway."


def check(p4, payload, when):
    """The hook output for a call about to run, or None: an earlier finding in place of a web call, an earlier
    failure before a command the model expects to fail, as the mode says. While `on`, every call that reaches it
    gets a row in `checks`, answered or not."""
    configure(p4)
    if not ON:
        return None
    tool = payload.get("tool_name") or ""
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    session, agent = payload.get("session_id") or "", payload.get("agent_id") or ""
    k, key = kind(tool), key_of(tool, inp)
    mode = {"web": WEB, "shell": SHELL}.get(k, "shadow")
    con = connect(p4)
    try:
        action, score, shown, text = "silent", 0.0, "", ""
        if mode != "off" and k in ("web", "shell"):
            if con.execute("SELECT 1 FROM pending WHERE session=? AND agent=? AND key=?", (session, agent, key)).fetchone():
                con.execute("DELETE FROM pending WHERE session=? AND agent=? AND key=?", (session, agent, key))
                action = "again"
            else:
                if k == "web":
                    score, row, thr = web_match(con, p4, tool, inp, when)
                    found = [row] + getattr(web_match, "also", []) if row is not None and score >= thr else []
                    text = "\n\n".join(web_text(r) for r in found)
                    shown = row["id"] if text else ""
                else:
                    score, row, thr = shell_match(con, p4, tool, inp)
                    text = shell_text(row) if row is not None else ""
                    shown = row["sig"] if text else ""
                if text:
                    action = mode
                    if mode == "answer":
                        con.execute("INSERT OR REPLACE INTO pending VALUES (?,?,?,?)", (session, agent, key, when))
        con.execute("INSERT INTO checks VALUES (?,?,?,?,?,?,?,?)", (when, session, agent, tool, key, action,
                                                                   round(score, 4), shown))
        con.commit()
    finally:
        con.close()
    if action == "answer":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": text + AGAIN}}
    if action == "note":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}
    return None


# --- backfill from Claude Code's transcripts ----------------------------------------------------------------

def stamp(iso):
    """A transcript's UTC timestamp as the local `YYYY-MM-DD HH:MM` the hooks write, so backfilled and live rows
    stand on one clock."""
    import datetime
    try:
        t = datetime.datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        return t.astimezone().strftime("%Y-%m-%d %H:%M") if t.tzinfo else t.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return (iso or "")[:16].replace("T", " ")


def backfill(p4, roots, keep_tracked=True):
    """Every tool call of the transcripts under `roots` into the table, each tool_use id once, since a resumed or
    forked session repeats its history in a new file. With `keep_tracked`, web findings and fixed failures also go
    to the tracked file. Returns the number of rows written."""
    configure(p4)
    open_calls, done = {}, []
    for root in roots:
        for d, _, names in os.walk(root):
            for n in sorted(names):
                if not n.endswith(".jsonl"):
                    continue
                try:
                    f = open(os.path.join(d, n), encoding="utf-8", errors="replace")
                except OSError:
                    continue
                with f:
                    for line in f:
                        if '"tool_use"' not in line and '"tool_result"' not in line:
                            continue
                        try:
                            o = json.loads(line)
                        except ValueError:
                            continue
                        content = (o.get("message") or {}).get("content")
                        if not isinstance(content, list):
                            continue
                        for c in content:
                            if not isinstance(c, dict):
                                continue
                            if c.get("type") == "tool_use" and c.get("id") and c["id"] not in open_calls:
                                open_calls[c["id"]] = {
                                    "id": c["id"], "tool": c.get("name") or "", "inp": c.get("input") or {},
                                    "time": stamp(o.get("timestamp")), "session": o.get("sessionId") or "",
                                    "agent": o.get("agentId") or ("side" if o.get("isSidechain") else ""), "ok": None}
                            elif c.get("type") == "tool_result":
                                r = open_calls.get(c.get("tool_use_id"))
                                if r is None or r["ok"] is not None:
                                    continue
                                t = c.get("content")
                                r["text"] = flatten(t if t is not None else "")
                                r["ok"] = not c.get("is_error")
                                done.append(r)
    done.sort(key=lambda r: r["time"])
    con = connect(p4)
    written = 0
    try:
        for k, r in enumerate(done):
            if insert(con, r, p4 if keep_tracked else None):
                written += 1
            if k % 500 == 499:
                con.commit()               # in short transactions: a live session's hook waits 3 s for the database
        con.commit()
    finally:
        con.close()
    return written


# --- training -----------------------------------------------------------------------------------------------

def at_precision(scored, min_precision):
    """The lowest threshold at which five or more answered calls are right at least min_precision of the time:
    {threshold, precision, coverage, answered, right} over `[(score, right)]`, every call counted in coverage."""
    best = {"threshold": None, "precision": 0.0, "coverage": 0.0, "answered": 0, "right": 0}
    hits = sorted((s for s in scored if s[0] > 0), key=lambda s: -s[0])
    right = 0
    for i, (s, y) in enumerate(hits):
        right += y
        if i + 1 < len(hits) and hits[i + 1][0] == s:
            continue
        if i + 1 >= 5 and right / (i + 1) >= min_precision:
            best = {"threshold": round(s, 4), "precision": round(right / (i + 1), 4),
                    "coverage": round((i + 1) / max(1, len(scored)), 4), "answered": i + 1, "right": right}
    return best


def fold_of(session, folds):
    return int(hashlib.sha1((session or "").encode("utf-8")).hexdigest()[:8], 16) % folds


def fit_named(examples, epochs=None, lr=0.5, l2=1e-4):
    """Logistic regression over named features, full-batch gradient steps with positives weighed to balance."""
    if not examples:
        return {}
    epochs = EPOCHS_WEB if epochs is None else epochs
    pos = sum(y for _, y in examples) or 1
    wpos = (len(examples) - pos or 1) / pos
    w = {}
    for _ in range(epochs * 10):
        g = {}
        for x, y in examples:
            e = (lin(w, x) - y) * (wpos if y else 1.0)
            for k, v in x.items():
                g[k] = g.get(k, 0.0) + e * v
        for k, v in g.items():
            w[k] = w.get(k, 0.0) - lr * (v / len(examples) + l2 * w.get(k, 0.0))
    return w


def web_pairs(rows):
    """For every web call whose question has words: its session, and for each earlier call of the same tool and
    target, as `web_candidates` takes them, the matcher's score, the pair's features and its label. The label is
    free: the later call ran, so its own result says whether the earlier finding would have answered it."""
    toks = [ranker.tokens(r["ask"]) for r in rows]
    finds = [ranker.tokens(r["finding"]) for r in rows]
    idf, fidf = idf_from(toks), idf_from(finds)
    out = []
    for i, r in enumerate(rows):
        if not toks[i]:
            continue
        cands = []
        for j in range(i):
            o = rows[j]
            if o["tool"] != r["tool"] or o["target"] != r["target"]:
                continue
            days = ranker.days_between(o["time"], r["time"])
            x = pair_features(toks[i], r["tool"], toks[j], finds[j], days, idf)
            y = 1 if cos(finds[i], finds[j], fidf) >= LABEL_COS else 0
            cands.append((x["cos"], x, y))
        out.append((r["session"], cands))
    return out


def train_web(con, folds, min_precision):
    calls = web_pairs(web_rows(con))
    matcher, model = [], []
    for f in range(folds):
        train = [(x, y) for s, cands in calls if fold_of(s, folds) != f for _, x, y in cands]
        w = fit_named(train) if train else {}
        for s, cands in calls:
            if fold_of(s, folds) != f:
                continue
            if not cands:
                matcher.append((0.0, 0))
                model.append((0.0, 0))
                continue
            m = max(cands, key=lambda c: c[0])
            matcher.append((m[0], m[2]))
            scored = [(lin(w, x), y) for _, x, y in cands]
            model.append(max(scored, key=lambda c: c[0]))
    rm, rw = at_precision(matcher, min_precision), at_precision(model, min_precision)
    full = fit_named([(x, y) for _, cands in calls for _, x, y in cands])
    savable = sum(1 for _, cands in calls if any(y for _, _, y in cands))
    return {"calls": len(calls), "with_candidates": sum(1 for _, c in calls if c), "savable": savable,
            "pairs": sum(len(c) for _, c in calls), "matcher": rm, "model": rw, "w": full,
            "promoted": bool(rw["answered"] > rm["answered"] and rw["threshold"] is not None)}


def train_shell(con, min_precision, test_share=0.2):
    """The failure model: fitted on the earlier commands and tested on the later ones, in time order, unshuffled."""
    rows = con.execute("SELECT tool, ask, ok, sig, session FROM calls WHERE kind='shell' ORDER BY time, rowid").fetchall()
    if len(rows) < 200:
        return {"calls": len(rows), "threshold": None}
    cut = int(len(rows) * (1 - test_share))
    ex = [(shell_features(r["ask"], r["tool"]), 0 if r["ok"] else 1) for r in rows]
    w = ranker.fit(ex[:cut], epochs=EPOCHS_SHELL)
    known = {r["sig"] for r in rows[:cut] if not r["ok"] and r["sig"]}
    scored = [(ranker.score(w, x), y) for x, y in ex[cut:]]
    res = at_precision(scored, min_precision)
    fails = sum(y for _, y in ex[cut:])
    known_fails = sum(1 for r in rows[cut:] if not r["ok"] and r["sig"] in known)
    return {"calls": len(rows), "tested": len(rows) - cut, "failed": fails, "known_signature": known_fails,
            "base_rate": round(fails / max(1, len(rows) - cut), 4), **res,
            "top100_precision": round(sum(y for _, y in sorted(scored, reverse=True)[:100]) / 100.0, 4),
            # the weights are kept only when a threshold passed: a model that cannot answer is not shipped
            "w": {str(k): round(v, 5) for k, v in ranker.fit(ex, epochs=EPOCHS_SHELL).items() if abs(v) > 1e-4}
            if res["threshold"] is not None else {}}


def train(p4, folds=5, now=None):
    """One round: both web roads held out by session and the failure model tested forward in time. The model file
    is written when the matcher or either model found a threshold, and the round's figures are appended to
    lookups-eval.tsv and returned."""
    configure(p4)
    con = connect(p4)
    try:
        web = train_web(con, folds, MIN_PRECISION)
        shell = train_shell(con, MIN_PRECISION)
    finally:
        con.close()
    when = now or time.strftime("%Y-%m-%d %H:%M")
    model = {"kind": MODEL_KIND, "version": 1, "trained": when,
             "web": {"w": {k: round(v, 5) for k, v in web["w"].items()}, "threshold": web["model"]["threshold"],
                     "matcher_threshold": web["matcher"]["threshold"], "promoted": web["promoted"]},
             "shell": {"w": shell.get("w") or {}, "threshold": shell.get("threshold")}}
    promoted = web["promoted"] or shell.get("threshold") is not None
    if promoted or web["matcher"]["threshold"] is not None:
        ranker.write_atomic(model_path(p4), json.dumps(model, separators=(",", ":")))
    out = {"calls": web["calls"], "with_candidates": web["with_candidates"], "savable": web["savable"],
           "pairs": web["pairs"], "matcher": web["matcher"], "model": web["model"], "promoted": web["promoted"],
           "shell": {k: v for k, v in shell.items() if k != "w"}, "time": when}
    import labels as lb
    head = ["time", "web_calls", "savable", "matcher", "model", "promoted", "shell_tested", "shell_failed", "shell"]
    lb.append_tsv(p4conf.sub(p4, "models", EVAL), head, [{
        "time": when, "web_calls": web["calls"], "savable": web["savable"],
        "matcher": json.dumps(web["matcher"], separators=(",", ":")), "model": json.dumps(web["model"], separators=(",", ":")),
        "promoted": "model" if web["promoted"] else "matcher", "shell_tested": shell.get("tested", 0),
        "shell_failed": shell.get("failed", 0),
        "shell": json.dumps({k: v for k, v in shell.items() if k != "w"}, separators=(",", ":"))}])
    out["written"] = os.path.exists(model_path(p4))      # the file also carries the matcher's trained threshold
    return out


def report(p4):
    con = connect(p4)
    try:
        out = {"calls": con.execute("SELECT COUNT(*) FROM calls").fetchone()[0],
               "by_kind": dict(con.execute("SELECT kind, COUNT(*) FROM calls GROUP BY kind").fetchall()),
               "failed": con.execute("SELECT COUNT(*) FROM calls WHERE ok=0").fetchone()[0],
               "fixed": con.execute("SELECT COUNT(*) FROM calls WHERE ok=0 AND fix!=''").fetchone()[0],
               "findings": con.execute("SELECT COUNT(*) FROM calls WHERE kind='web' AND finding!=''").fetchone()[0],
               "checks": dict(con.execute("SELECT action, COUNT(*) FROM checks GROUP BY action").fetchall())}
    finally:
        con.close()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("backfill", "train", "report"):
        s = sub.add_parser(name)
        s.add_argument("--p4", required=True, help="the store: <repository>/.claude/p4")
        if name == "backfill":
            s.add_argument("roots", nargs="+", help="transcript directories, such as ~/.claude/projects/<project>")
        if name == "train":
            s.add_argument("--folds", type=int, default=5)
    a = ap.parse_args(argv)
    if a.cmd == "backfill":
        print(json.dumps({"written": backfill(a.p4, a.roots), **report(a.p4)}, indent=1))
    elif a.cmd == "train":
        print(json.dumps(train(a.p4, a.folds), indent=1))
    else:
        print(json.dumps(report(a.p4), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
