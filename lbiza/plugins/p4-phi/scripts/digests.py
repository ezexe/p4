#!/usr/bin/env python3
"""digests.py: one corpus entry for each session that is no longer live, in `phi/store/digests/<its folder's name>.md`.

A later session retrieves of an earlier one only its message rows, each a prompt and the head of its reply. The
digest holds what the session was asked, what it showed done and reported, the findings and decisions it kept as
notes, the files it changed, the heads it left and the plan steps it left open. It is built from the records p4-phi
keeps of the session and tracks when `phi.track` is on, `session.json`, `turns.jsonl`, `notes.jsonl` and `plan.json`,
and from nothing else: no transcript, no `log.jsonl`, no `session.md`, no command a turn ran and no tool output.

No hook runs when ezexe archives a session in the app, and SessionEnd is not known to fire there, so nothing is
written at the archive itself. `sweep` runs inside the async `train` entry of Stop, at most once in SWEEP_GAP_S for a
store: it writes the digest of every session whose own record or the app's says it is no longer live and whose
records are newer than its digest. A session archived a year ago is written at the next sweep, and one that was
revived and closed again is written again, whole, in the same file.

The entry is dated at the session's last turn, so training never shows it to a task that came before it. It holds
no time of writing and asks git nothing, so the same records give the same text on one machine.
"""

import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import ranker  # noqa: E402
import relay  # noqa: E402
import rows  # noqa: E402
import store as st  # noqa: E402

SWEEP_GAP_S = 300.0              # the least time between two sweeps of one store
SWEEP_MOST = 40                  # the digests one sweep writes; the rest wait for the next
SWEEP_S = 10.0                   # what one sweep may take
RECORDS = ("turns.jsonl", "notes.jsonl", "plan.json")     # a digest older than any of these is written again
TITLE_CHARS = 200
ASKED_CHARS = 300                # as rows.FP_CHARS cuts a message row's prompt
DONE_CHARS = 300
REPORTED_CHARS = 600
NOTE_CHARS = 240
SOURCE_CHARS = 80
NOTES_MOST = 8                   # the newest notes kept
FILES_MOST = 12
PATH_CHARS = 120
HEADS_MOST = 4
OPEN_MOST = 6
STEP_CHARS = 100
DIGEST_BYTES = 12000             # a digest file is never larger, and one read takes it whole
SCRUB_CHARS = 8000               # what line() reads of a record's text before it scrubs and cuts it

# a string shaped like a credential: a private key block, a token by its issuer's prefix, a JSON web token, an
# authorization value, and whatever follows a name that says token, secret, password or api key
SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"
    r"|\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,})"
    r"|(?i:\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{16,})"
    r"|(?i:\b[\w.-]*(?:token|secret|password|passwd|api[_-]?key)[\w.-]*\s*[=:]\s*[\"']?)[A-Za-z0-9._~+/=-]{12,}",
    re.S)


def scrub(text):
    """A record's text without its fenced blocks, where tool output is pasted, and with every credential-shaped
    string replaced."""
    return SECRET.sub("[redacted]", rows.FENCE_RE.sub(" ", str(text or "")))


def line(text, n):
    """`text` scrubbed, on one line, and at most `n` characters long. Only its first SCRUB_CHARS characters are
    read, so the patterns never run over a text of any length."""
    s = " ".join(scrub(str(text or "")[:SCRUB_CHARS]).split())
    return s if len(s) <= n else s[:max(0, n - 3)].rstrip() + "..."


def closed(s):
    """True when a session is no longer live, by the signs relay.gone reads: its record says stale, counted as
    archived or archived, or the app has it archived. Nothing is written here."""
    return bool(s.get("stale") or s.get("doneRetired") or s.get("archived")) or relay.archived_in_app(s)


def turns_of(home, sid):
    """A session's turns, oldest first, each once as it last finished, as phi.load_turns reads them."""
    by = {}
    for r in relay._rows(os.path.join(relay._dir(home, sid), "turns.jsonl")):
        if r.get("id"):
            by[r["id"]] = r
    return list(by.values())


def pairs_of(home, sid, s, most=1.0):
    """The digest entry's fields for a session, None for one with no kept turn. `most` scales how many notes and
    files and how much of the report are kept, for a digest that came out too large."""
    import plans
    turns = turns_of(home, sid)
    if not turns:
        return None
    base = s.get("cwd") or ""
    last = turns[-1]
    report = next((str(t.get("report")) for t in reversed(turns)
                   if str(t.get("report") or "").strip() and not relay.BARE.match(str(t.get("report")))), "")
    done = s.get("done") if isinstance(s.get("done"), dict) else {}
    notes = [n for n in relay._rows(os.path.join(relay._dir(home, sid), "notes.jsonl"))
             if not str(n.get("claim") or "").lower().startswith("replaces:")]   # that note is about another session
    keep = int(NOTES_MOST * most)
    decided, found = [], []
    for n in (notes[-keep:] if keep else []):
        src = line(n.get("source"), SOURCE_CHARS)
        text = line(n.get("claim"), NOTE_CHARS) + (f"; source: {src}" if src else "")
        (decided if str(n.get("kind") or "") == "decision" else found).append(text)
    files = relay.edited_files(home, sid)
    changed = [line(relay.show(f, base), PATH_CHARS) for f in files[:int(FILES_MOST * most)]]
    heads = {}
    for t in turns:
        for h in (t.get("delta") or {}).get("heads") or []:
            repo, _, sha = str(h).rpartition(" ")
            heads[repo] = sha
    still = [f"step {x.get('addr')} {line(x.get('content'), STEP_CHARS)}, {x.get('status') or 'pending'}"
             for x in plans.load(home, sid).get("steps") or []
             if isinstance(x, dict) and x.get("status") != "completed"]
    pairs = [("digest", line(relay._title(s), TITLE_CHARS)), ("time", str(last.get("time") or "")[:16]), ("id", sid),
             ("asked", line(s.get("task") or turns[0].get("prompt"), ASKED_CHARS)),
             ("done", line(done.get("text") or last.get("done"), DONE_CHARS)),
             ("reported", line(report, int(REPORTED_CHARS * most)) if most else ""),
             ("decided", "\n".join(decided)), ("found", "\n".join(found)),
             ("changed", ", ".join(changed) + (" ..." if changed and len(files) > len(changed) else "")),
             ("heads", ", ".join(line(relay.show_head(f"{r} {v}", base), PATH_CHARS)
                                 for r, v in list(heads.items())[:HEADS_MOST])),
             ("open", "; ".join(still[:OPEN_MOST]))]
    return pairs[:3] + [(k, v) for k, v in pairs[3:] if v]


def text_of(home, sid, s, name):
    """The whole digest file of a session, at most DIGEST_BYTES long, None for a session with no kept turn."""
    text = None
    for most in (1.0, 0.5, 0.0):
        pairs = pairs_of(home, sid, s, most)
        if pairs is None:
            return None
        text = st.render(f"{st.DIGESTS}/{name}.md", [pairs])
        if len(text.encode("utf-8")) <= DIGEST_BYTES:
            break
    return text


def newest_of(d):
    """The newest mtime among a session folder's RECORDS, 0 where it has no turns.jsonl."""
    try:
        new = os.stat(os.path.join(d, RECORDS[0])).st_mtime_ns
    except OSError:
        return 0
    for n in RECORDS[1:]:
        try:
            new = max(new, os.stat(os.path.join(d, n)).st_mtime_ns)
        except OSError:
            pass
    return new


def owed(d, out):
    """True when the session folder `d` has turns and its digest `out` is missing, older than a record of RECORDS,
    or holds anything but one entry, as a merge of two machines' digests can leave it."""
    new = newest_of(d)
    if not new:
        return False
    try:
        if os.stat(out).st_mtime_ns < new:
            return True
        return sum(1 for l in st.read_text(out).split("\n") if st.HEAD_RE.match(l)) != 1
    except OSError:
        return True


def write_one(p4, home, name, project, shared):
    """Writes the digest of the session in the folder `name` when it is owed and the session is no longer live, and
    returns the session's id, '' where nothing was written."""
    d = os.path.join(home, "phi", "sessions", name)
    out = os.path.join(st.store_dir(p4), st.DIGESTS, name + ".md")
    if not owed(d, out):
        return ""
    s = relay._read_json(os.path.join(d, "session.json"))
    sid = str(s.get("sessionId") or "")
    if not sid or not closed(s):
        return ""
    if shared:
        cwd = relay.norm(s.get("cwd"))
        if not (cwd == project or cwd.startswith(project + "/")):
            return ""
    text = text_of(home, sid, s, name)
    if text is None:
        return ""
    try:
        same = st.read_text(out) == text
    except OSError:
        same = False
    if same:
        os.utime(out)                    # its records were touched and say the same: looked at, not written
        return ""
    ranker.write_atomic(out, text)
    return sid


def sweep(p4, gap=SWEEP_GAP_S):
    """Writes the digest of every session of the store `p4` that is no longer live and whose digest is owed, and
    returns the ids written. At most once in `gap` seconds for a store, by the time of a stamp file git ignores, at
    most SWEEP_MOST digests and SWEEP_S seconds a sweep. A session whose digest is as new as its records costs
    four stats and one read of the digest. A session whose records cannot be read or whose digest cannot be
    written is passed over, so it stops no other. Where the session tree lives in a shared store, only the
    sessions whose folder is this project are written here."""
    stamp = p4conf.sub(p4, "models", "digest-sweep.tmp")
    try:
        if gap and time.time() - os.stat(stamp).st_mtime < gap:
            return []
    except OSError:
        pass
    ranker.write_atomic(stamp, time.strftime("%Y-%m-%d %H:%M") + "\n")
    home = relay.tree_home(p4)[0] or p4
    base = os.path.join(home, "phi", "sessions")
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    project = relay.norm(os.path.dirname(os.path.dirname(os.path.abspath(p4))))
    shared = relay.norm(os.path.abspath(home)) != relay.norm(os.path.abspath(p4))
    wrote, end = [], time.time() + SWEEP_S
    for name in names:
        if len(wrote) >= SWEEP_MOST or time.time() > end:
            break
        try:
            sid = write_one(p4, home, name, project, shared)
        except Exception:  # noqa: BLE001 — one session's broken record never costs the others their digests
            continue
        if sid:
            wrote.append(sid)
    return wrote
