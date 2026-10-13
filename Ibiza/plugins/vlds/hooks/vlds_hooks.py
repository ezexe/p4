#!/usr/bin/env python3
"""vlds_hooks.py — the VLDS plugin's hook bodies: mechanical and judgment-free, in the phi.py mold.

Subcommands, each reading the harness's JSON payload on stdin (decoded as UTF-8 — the harness writes UTF-8
whatever the console codepage says):
  session-open            SessionStart, the recall's index slot: print the clock (`now:`), the recall mode, a
                          digest of phi-index.md (register, hot rows, updated), a digest line per hot file, the
                          owner-voice digest, and the verdict of `phi.py check`. In the POOLED mode — the
                          default — the hot files are not injected at all: the slot prints the directive under
                          which the judged store operations are the operator subagent's (hooks/operator-prompt.md
                          is its brief) and its derivation is what the model acts on — open (the pool at the first
                          prompt per hooks/pool-prompt.md, scoped to the task the model derives in one line, pulled
                          into context in place of the files; the barrier on a candidate row; the intent of an
                          unknown short message) and sweep (scoring what is cold; scripts/normalize.py --pour places
                          it) — while the close is mechanical: the model writes the turn's record and
                          scripts/record.py applies it. One operator per session, continued for at most
                          `operator-moments:` moments then relaunched. `pool: inject` in the index's `## recall`
                          section restores the slot injection of every inject file; `operator-model:`, `pool-model:`,
                          `pool-child-model:` (the pool's child readers, one per file, launched by the operator
                          per hooks/pool-child-prompt.md) and `sweep-model:` name the models; `pool-road:` picks
                          children (the default: the skeleton phi.py pool writes, one pick-reader per file,
                          streamed), skeleton (one judged pass), or single; `operator-via:` names an agent the
                          session hands every operator moment to instead, which launches the operator itself and
                          returns a derived understanding. On
                          `source` resume, fork, or compact print only the clock, the digest lines, and the
                          verdict — the conversation already holds its own recall — and on a compact re-inject
                          store/recall-pool.md when it is this session's, since the compaction may have
                          summarized the recall away; and record the session id in `.sessions`, so a fork's
                          first prompt (a new id over a live conversation) and a pre-hook session's next prompt
                          do not pour rows that are still live.
  session-open --standing N
                          SessionStart, the owner's standing rules whole (the pooled mode only): every LIVE form
                          ruling and every-turn index rule, uncut, as `phi.py standing` prints them, in an output
                          of its own so the harness's per-hook cap is its only limit; part N when they outgrow
                          one output, nothing past the end. Every source prints it, since a resumed or compacted
                          conversation may predate the block or have summarized it away.
  session-open --slot N   SessionStart, one chunk slot (the `pool: inject` mode only; silent when pooled): the
                          index's `inject:` files are split at entry boundaries into chunks under the harness's
                          per-hook output cap, and slot N prints the N-th chunk (header with the first chunk of
                          each file). Nothing on resume / fork / compact, nothing when the plan is shorter than
                          N+1. One hook per slot, because the harness caps EACH hook's output at 10,000
                          characters: one process printing everything would be spilled to a file and replaced by
                          a preview. A single entry over the cap, or a chunk beyond the registered slots, arrives
                          as a marker line to read by hand.
  prompt-open             UserPromptSubmit: print the clock, stamp the message's dispatch row (fingerprint /
                          time / arrival) and run the mechanical half of the dispatch barrier: when no earlier
                          row's fingerprint resembles the message (token overlap under BARRIER_JACCARD, or not
                          identical for a message under BARRIER_MIN_TOKENS tokens) the row gets `state: FRESH`
                          here; when one does, the candidate is named and `state:` is left for the operator
                          subagent's judgment — ECHO, SUPERSEDED, or a fresh ask that merely reads alike. A
                          message of at most SHORT_WORDS words is called short: one the store's owner corpus
                          already holds KNOWN_SHORT_MIN times is a known command — never a candidate, its last
                          addressed: printed as the derivation, no operator — and an unknown one goes to the
                          operator for its intent before the model answers; `addressed:` is the record's at the
                          turn's close. A
                          task notification (a background task's completion, delivered as a prompt) is never an
                          ask, and neither is an agent's message (a report from the session's own subagent — the
                          operator's stream lines): such a row is stamped complete on arrival — arrival `task
                          notification` or `agent message`, FRESH, addressed as consumed — because a row left
                          open there would be closed by an operator whose own completion arrives the same way,
                          a loop with no floor.
                          The store is the session's own (`.claude/p4/sessions/<s8>/vlds/`, scripts/partition.py):
                          its dispatch.md and briefs.md are seeded there when absent, and nothing is ever poured
                          or dated — the session directory is the session's record. Every output names the
                          session by its short id and, when the transcript's last custom-title record gives one,
                          its chat title — the id stays for reference because a title can change, and .sessions
                          maps id to title; when the transcript lags the hook (it is written asynchronously), the
                          title .sessions recorded at an earlier prompt is used.
  pre-write               PreToolUse: when a Write, Edit, Bash, or PowerShell call is about to write a file
                          that carries a store file's NAME, ask before it lands anywhere but a `.claude/p4/sessions/<s8>/vlds/`
                          directory (the path is resolved against the call's cwd and any `cd` earlier in the
                          same command — a bare `ledger.md` that was true under one `cd` is false under
                          another), ask before a persisted entry carries a placeholder `time:` (`12:4x`,
                          `TBD`) instead of a stamp copied from the stream's `now:`, and ask before one carries
                          a `time:` guessed AHEAD of the clock — later than the write's own `now:` by more than
                          a minute (one session stamped rows up to fifty minutes ahead). Silent otherwise. Always
                          `ask`, never `deny`: `index.md` and `ledger.md` are legitimate names in a docs tree,
                          and only the user can say which this one is.
  pre-ask                 PreToolUse on AskUserQuestion and any mcp__*__show_widget: when briefs.md holds a
                          standing label (a class the owner ruled standing at its second instance), every
                          option's brief — a widget's `.elicit-pill` inner text, a panel option's description
                          — must carry one `<label>:` line; a picker missing one is DENIED with the labels, the
                          count that made each standing, and the options that lack them, so the model re-issues
                          the informed picker and the owner never sees the thin one. Keyed once per picker
                          fingerprint (the widget's title, the panel's question texts) in store/.pre-ask: the
                          re-issue passes even if still thin — a bounce is a nudge, not a wall. Silent when
                          nothing is standing, when every option carries every label, and on meta options
                          (all of the above, other). The recorder half is prompt-open's: a prompt that is neither
                          the elicitation shell's submit line nor its skip, arriving right after a served
                          picker, is stamped `kind: detail-ask` / `on: <picker>` (a submit whose textbox carries
                          a question, `kind: submit+detail-ask`), and the close names the omitted class in
                          briefs.md — the judgment no hook can make, since transcripts keep no reasoning; a
                          picker's submit or skip whose resembling rows are all addressed is written FRESH by
                          construction, never handed to the operator.
  pre-agent               PreToolUse on Agent: when the index's `operator-via:` names a conductor, a main-context
                          Agent call carrying the operator brief (hooks/operator-prompt.md) to any other agent
                          type, or to the conductor without its `conductor: launch the operator …` line, is
                          DENIED with the call to make instead — once per call fingerprint in store/.pre-agent,
                          so a re-issue passes (a conductor missing from the session's agent types is launched
                          around, and said so). Silent inside a subagent (`agent_id`), where the conductor
                          launches the operator itself.
  post-write             PostToolUse: when a Write, Edit, Bash, or PowerShell call touched the store, or wrote
                          a store-named file anywhere, print the clock and run `phi.py check`, handing its
                          verdict back as additionalContext — a mis-homed write is followed at once by a check
                          whose `[STRAY]` line names the file. The full verdict is handed back when it differs
                          from the last one this session saw; an unchanged verdict comes back as one line, so a
                          turn of store writes does not re-paste the same debt list into the context each time.
                          Then the always-on collector's write barrier — `phi.py trace`: every hot entry new since
                          the last trace is traced against the tombstone masks, and each finding is one `gc:` line
                          — a new entry a tombstone masks (freed garbage allocated again), or a new tombstone's
                          reach and the live entries holding a handle to what it freed (their pre-finalizers owed
                          this turn). Nothing found: no line.
  turn-close              Stop: first the always-on collector's finalization — the write barrier's trace once
                          more, for any write no post-write saw (a hand edit, a script outside a tool call) — then
                          the light normalize sweep, mechanical — scripts/normalize.py --light under the
                          sweep lock: attach a hook-poured dispatch record where a live segment has room, expire
                          and pour the virtual entries another session minted, pour the logger's oldest past its
                          budget — every step through phi.py's gates — then leave its one-line report in
                          store/.turn-close for the next prompt hook to print, since a Stop hook's stdout never
                          reaches the model. Nothing to move: silent. Lock held elsewhere: skipped, said so.

Everything here is mechanical. The stamp carries no judgment; the pour moves a file whose every entry belongs to
a conversation that is not this one (a new id that reaches its first prompt unrecorded) and destroys nothing (the
copy is verified before the reseed, and the copy stays); the check only reports; the pre-write gate only asks.
What the hooks never do: register the poured file in the index (a sweep's judged act), pour any other hot file
by judgment (the light classes are counted, not scored), judge a dispatch row (the hook writes FRESH only when no
earlier row resembles the message; the judged state and addressed are the operator subagent's), delete or move a
stray file (the user disposes of it), or block a prompt — every failure prints a one-line notice and exits 0.

The clock: every subcommand's output carries a `now: YYYY-MM-DD HH:MM` line, so a store write anywhere in the
turn has an authoritative stamp to copy — the model never guesses a digit.

First-prompt detection: `<store>/.sessions` holds one line per session id that has submitted a prompt or been
recorded at a resume / fork / compact start. An id absent from it at its first prompt is a new session; a resumed
conversation keeps its id, a fork is recorded at its SessionStart, and a transient SessionStart firing never
submits a prompt — so a live conversation's rows are never poured out from under it.
"""

import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import partition as pt  # noqa: E402 — scripts/partition.py: which store files live in a session's own directory

DEFAULT_INJECT = ["local-storage.md", "index.md", "tombstones.md", "ledger.md", "session-storage.md",
                  "virtual.md", "briefs.md"]
DEFAULT_DIGEST = ["data-store.md", "logger.md"]
LOCK_STALE_S = 3600
FINGERPRINT_CHARS = 200
HOOK_OUTPUT_CAP = 10000     # the harness's per-hook output cap, in characters
SLOT_BUDGET = 9500          # what one slot may print, head line included, to stay under the cap
SLOT_HEAD = 200             # reserved for the slot's head line when chunking
SLOTS = 12                  # slots hooks.json registers: --slot 0 .. --slot 11
HELD_SOURCES = ("resume", "fork", "compact")   # SessionStart sources whose conversation holds its own recall
# the store's file names — the same set as scripts/phi.py STORE_FILES; a file carrying one of these names
# outside a `.claude/p4/sessions/<s8>/vlds/` directory is what the pre-write gate asks about and the check reports as [STRAY]
STORE_FILES = {"dispatch.md", "index.md", "ledger.md", "logger.md", "tombstones.md", "virtual.md",
               "session-storage.md", "local-storage.md", "data-store.md", "phi-index.md", "recall-pool.md",
               "briefs.md"}
BRIEFS_FILE = "briefs.md"           # what a picker left out, named when the owner asked — hooks/briefs-seed.md
PRE_ASK_SEEN = ".pre-ask"           # picker fingerprints the pre-ask gate has bounced once; the re-issue passes
PRE_AGENT_SEEN = ".pre-agent"       # operator hand-offs the pre-agent gate has bounced once; the re-issue passes
# the two picker tools — the closing's built widget and the fork's native panel — as PreToolUse names them
PICKER_TOOL_RE = re.compile(r"^(AskUserQuestion|mcp__[A-Za-z0-9_-]+__show_widget)$")
# the elicitation shell's own submit line ("<Title> details — Label: value · Label: value") and its skip
SUBMIT_RE = re.compile(r"^(.{1,120}?) details — (.+)$")
SKIP_RE = re.compile(r"^\(Skipped the form\b")
# the acts page's submit: the prompt it assembles ends with this marker (skills/acts-widget/assemble.js), its
# title rides in the opening paragraph, and the owner's per-act context is where a riding question would sit
ACTS_MARK_RE = re.compile(r"<!-- acts-widget round=(\d+) picked=([^ ]*) -->")
ACTS_TITLE_RE = re.compile(r"from your closing widget \(“(.{1,120}?)”\)")
ACTS_NOTE_RE = re.compile(r"My added context for this act: (.*?)(?= ### | <!-- acts-widget |$)")
NOW_FMT = "%Y-%m-%d %H:%M"
POOL_FILE = "recall-pool.md"        # the recall subagent's pooled report — derived, one per store, session-named
POOL_MODES = ("subagent", "inject")
DEFAULT_POOL = "subagent"
DEFAULT_OPERATOR_MODEL = "sonnet"   # the operator's open moment (barrier, intent); the index's `operator-model:` overrides
DEFAULT_POOL_MODEL = "sonnet"       # the pool, once per session — the one judged read a whole session leans on; `pool-model:`
DEFAULT_SWEEP_MODEL = "sonnet"      # the sweep moment's scoring; `sweep-model:`
DEFAULT_POOL_CHILD_MODEL = "haiku"  # the pool's child readers, one per read-list file, launched by the operator; `pool-child-model:`
POOL_ROADS = ("children", "skeleton", "single")   # `pool-road:` — the skeleton with one child pick-reader per file,
DEFAULT_POOL_ROAD = "children"                    # streamed; the skeleton for one judged pass; or the operator alone
DEFAULT_OPERATOR_MOMENTS = 4        # continuations before a fresh launch, so a grown context stops compounding; `operator-moments:`
DEFAULT_OPERATOR_VIA = None          # the agent a session hands every operator moment to, which launches the operator itself
                                     # and returns a derived understanding; `operator-via:` names its agent type, absent = none
KNOWN_SHORT_MIN = 2                 # a short message seen this many times in the store's owner corpus is a known command
BARRIER_MIN_TOKENS = 3      # a message with fewer tokens matches an earlier row only when identical
BARRIER_JACCARD = 0.5       # token overlap at or above which an earlier row is a candidate for the operator's judgment
SHORT_WORDS = 5             # a message of at most this many words is called short: the operator derives its intent
TURN_CLOSE = ".turn-close"          # the Stop hook's reports, one line per session, printed by the next prompt hook
TURN_CLOSE_BUDGET_S = 55            # the Stop hook's own deadline, under the 60 s hooks.json gives it; every call shares it
TURN_CLOSE_MIN_CALL_S = 5           # a call with less time left than this waits for the next turn close
VERDICT_MAX_AGE_S = 86400           # a cached shadow or refusal verdict is re-earned at least once a day
CHECK_LAST = ".check-last"          # the last check summary each session saw, so an unchanged one comes back as a line
VOICE_CAP = 1200            # the owner-voice digest's size cap, in characters
VOICE_TOKEN_WORDS = 3       # a message of at most this many words counts as an adoption token
VOICE_TOKENS = 10           # how many adoption tokens the digest lists
VOICE_RULINGS = 5           # how many delivery-form rulings the digest lists
VOICE_FORM_WORDS = ("fence", "file", "message", "artifact", "text box")


def payload_from_stdin():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def resolve_store(payload):
    """This session's store: `<project>/.claude/p4/sessions/<s8>/vlds` (scripts/partition.py has the layout)."""
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    return pt.session_store(os.path.join(root, ".claude", "p4"), payload.get("session_id") or "unknown")


def plugin_root():
    return os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def idb_module():
    """scripts/idb.py, the keyspace engine — None when it cannot be imported, and every hook path then takes the
    φ-register's road, as it always did."""
    try:
        scripts = os.path.join(plugin_root(), "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import idb  # noqa: E402
        return idb
    except Exception:  # noqa: BLE001 — a hook degrades, never raises
        return None


def phi_module():
    """scripts/phi.py, the store's mechanical companion — None when it cannot be imported."""
    try:
        scripts = os.path.join(plugin_root(), "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import phi  # noqa: E402
        return phi
    except Exception:  # noqa: BLE001 — a hook degrades, never raises
        return None


def gc_trace_lines(store, sid):
    """The write barrier's trace (`phi.py trace`) — one `gc:` line per finding, [] when nothing was found or the trace
    could not run (a failure is one line, never a raise): what the always-on collector owes the turn it runs in."""
    m = phi_module()
    if m is None or not os.path.isdir(store):
        return []
    try:
        findings, _baseline = m.gc_trace(store, sid)
        return m.trace_lines(findings)
    except Exception as e:  # noqa: BLE001
        return [f"gc: the write barrier's trace could not run — {type(e).__name__}: {e}"]


def store_engine(store):
    """(engine, setting, state) from the index's `index-engine:` and what is on disk — engine 'idb' (the keyspace
    runs), 'phi', 'shadow' (φ runs, a shadow migration reports), 'migrate' (a φ store owed its migration); φ when the
    engine file is unreadable."""
    m = idb_module()
    try:
        if m is not None:
            return m.resolve(store)
    except Exception:  # noqa: BLE001
        pass
    idb_dir = os.path.join(store, "idb")
    runs = os.path.join(idb_dir, "runs")
    if os.path.exists(os.path.join(idb_dir, "keys.tsv")) or (os.path.isdir(runs) and os.listdir(runs)):
        return "idb", "unknown", "idb"      # on the keyspace, the engine unreadable: never the φ road
    return "phi", "phi", "unknown"


def session_dispatch_records(store):
    """Every session's dispatch record, oldest session first — `sessions/<s8>/vlds/dispatch.md` in each session
    directory (the store alone outside the p4 layout). A pre-partition store's dated pours are copied into their
    owners' directories by hooks/p4-layout.sh and stay in the migrated store's cold tier as they were, so reading the
    directories alone counts each row once."""
    return [p for p in (os.path.join(s, "dispatch.md") for s in pt.session_stores(store)) if os.path.exists(p)]


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def write_bytes(path, data):
    with open(path, "wb") as f:
        f.write(data)


def sha12(data):
    return hashlib.sha256(data).hexdigest()[:12]


def session_title(payload):
    """The chat's title, from the transcript's last custom-title record — the app rewrites that record on every
    turn, so a rename lands; None when the payload names no transcript or the transcript carries no title."""
    path = payload.get("transcript_path")
    if not path or not os.path.exists(str(path)):
        return None
    title = None
    try:
        with open(str(path), encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"custom-title"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("type") == "custom-title" and rec.get("customTitle"):
                    title = " ".join(str(rec["customTitle"]).split())
    except OSError:
        return None
    return title or None


def ledger_title(store, sid):
    """The title `.sessions` last recorded for `sid`, or None — the fallback when the transcript lags the hook."""
    if not store:
        return None
    ledger = os.path.join(store, ".sessions")
    if not os.path.exists(ledger):
        return None
    for l in read_text(ledger).split("\n"):
        parts = l.split(" ", 3)
        if len(parts) > 3 and parts[0] == sid and parts[3].strip():
            return parts[3].strip()
    return None


def session_tag(payload, store=None):
    """(session id, display label, title) — the label is the short id followed by the chat's title in quotes
    when one is known: from the transcript's last custom-title record, else from what .sessions recorded at an
    earlier prompt (the transcript is written asynchronously and can lag the hook). The id stays for
    reference — a title can change — and the .sessions ledger maps one to the other."""
    sid = str(payload.get("session_id") or "unknown")
    title = session_title(payload) or ledger_title(store, sid)
    return sid, (f'{sid[:8]} "{title}"' if title else sid[:8]), title


def now_line(now):
    """The clock line every hook output carries — the one value a `time:` field is copied from."""
    return f"now: {now:{NOW_FMT}}"


def split_header(data):
    """Return (header_bytes, separator_bytes, body_bytes) at the first column-0 '---' line, or None."""
    for sep in (b"\n---\n", b"\n---\r\n"):
        i = data.find(sep)
        if i >= 0:
            return data[:i], sep, data[i + len(sep):]
    return None


def entry_lines(text, after_separator=True):
    """Column-0 '- ' lines — after the header separator when the text is a whole file, everywhere when the
    text is already a body (a stray '---' after the last entry must not hide the entries before it)."""
    lines = text.split("\n")
    start = 0
    if after_separator:
        try:
            start = lines.index("---") + 1
        except ValueError:
            start = 0
    return [l for l in lines[start:] if l.startswith("- ")]


def run_check(store):
    phi = os.path.join(plugin_root(), "scripts", "phi.py")
    if not os.path.exists(phi):
        return "phi.py not found beside the hooks — check skipped"
    try:
        r = subprocess.run([sys.executable or "python3", phi, "--store", store, "check"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=20)
    except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
        return f"phi.py check could not run: {e}"
    out = (r.stdout or "").strip()
    return out if out else f"phi.py check produced no output (exit {r.returncode})"


def check_summary(store):
    """The verdict line plus every CORRUPT, DEBT, and STRAY line; notes are counted, not listed."""
    out = run_check(store)
    lines = out.split("\n")
    keep = [l for l in lines if l.startswith("[CORRUPT]") or l.startswith("[DEBT]") or l.startswith("[STRAY]")
            or l.startswith(("phi.py check", "idb.py check"))]
    notes = sum(1 for l in lines if l.startswith("[note]"))
    if not keep:
        return out
    if notes:
        keep.append(f"({notes} note(s) withheld — judged-repair items; run `phi.py check` to list them)")
    return "\n".join(keep)


def record_seen(store, sid, now, title=None):
    """True when this session id was not yet in `.sessions`; records it either way as `sid time [title]`, the
    title refreshed on every prompt so a rename lands (a line without one keeps whatever it had)."""
    ledger = os.path.join(store, ".sessions")
    lines = [l for l in read_text(ledger).split("\n") if l.strip()] if os.path.exists(ledger) else []
    fresh, out = True, []
    for l in lines:
        parts = l.split(" ", 3)
        if parts[0] == sid and len(parts) >= 3:
            fresh = False
            kept = parts[3] if len(parts) > 3 else ""
            l = f"{parts[0]} {parts[1]} {parts[2]}" + (f" {title or kept}" if (title or kept) else "")
        out.append(l)
    if fresh:
        out.append(f"{sid} {now:{NOW_FMT}}" + (f" {title}" if title else ""))
    with open(ledger, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    return fresh


def seed_session_store(store):
    """A session store's two seeded files, when absent: the dispatch record and the briefs, from the plugin's seeds.
    Never overwritten — a user's edit is a ruling."""
    os.makedirs(store, exist_ok=True)
    for name, seed in (("dispatch.md", "dispatch-seed.md"), (BRIEFS_FILE, "briefs-seed.md")):
        target = os.path.join(store, name)
        src = os.path.join(plugin_root(), "hooks", seed)
        if not os.path.exists(target) and os.path.exists(src):
            write_bytes(target, read_bytes(src))


def session_store_label(store):
    """The store as a reader names it: `.claude/p4/sessions/<s8>/vlds/` inside the layout, the path outside."""
    s = pt.session_of(store)
    return f".claude/p4/sessions/{s}/vlds/" if s else store


# ─── the store-path matcher (pre-write and post-write share it) ─────────────────────────────────────────

_STORE_ALT = "|".join(re.escape(f) for f in sorted(STORE_FILES))
_QUOTED = r"(?:[A-Za-z]:)?[^\"'<>|;&\n]*?(?:%s)" % _STORE_ALT      # inside quotes: spaces allowed
_BARE = r"(?:[A-Za-z]:)?[^\s\"'<>|;&()`]*?(?:%s)" % _STORE_ALT     # unquoted: stops at whitespace
_PATH = r"(?:\"(%s)\"|'(%s)'|(%s))(?![\w.-])" % (_QUOTED, _QUOTED, _BARE)
_PY_PATH = r"(?:\"(%s)\"|'(%s)')" % (_QUOTED, _QUOTED)
# write positions in a shell command: redirects, tee, the PowerShell content cmdlets, python's open() in a
# write mode and Path().write_*; cp / mv / Copy-Item / Move-Item destinations are handled by COPY_RE
WRITE_RES = [
    re.compile(r">{1,2}[ \t]*" + _PATH),
    re.compile(r"\btee\b(?:[ \t]+-[A-Za-z]+)*[ \t]+" + _PATH),
    re.compile(r"\b(?:Set-Content|Add-Content|Out-File)\b[^\n|;]*?" + _PATH),
    re.compile(r"\bopen\(\s*" + _PY_PATH + r"\s*,\s*[\"'][aw]\+?b?[\"']"),
    re.compile(r"\bPath\(\s*" + _PY_PATH + r"\s*\)\.(?:write_text|write_bytes|open)\("),
]
COPY_RE = re.compile(r"\b(?:cp|mv|Copy-Item|Move-Item)\b((?:[ \t]+(?:-\S+|\"[^\"\n]*\"|'[^'\n]*'|[^\s;&|>]+))+)")
CD_RE = re.compile(r"(?:^|&&|\|\||;|\n)[ \t]*(?:cd|Set-Location|pushd)[ \t]+(?:\"([^\"\n]+)\"|'([^'\n]+)'|([^\s;&|]+))")
HEREDOC_RE = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[^\n]*\n(.*?)\n[ \t]*\2[ \t]*(?=\r?\n|$)", re.S)
PS_HERE_RE = re.compile(r"@(['\"])\r?\n(.*?)\r?\n\1@", re.S)
SH_QUOTED_RE = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"", re.S)
TIME_FIELD_RE = re.compile(r"^[ \t]*(?:- )?time:[ \t]*(.*?)[ \t]*$", re.M)
TIME_OK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?$")
P4_TAIL = os.path.normcase(os.sep + ".claude" + os.sep + "p4")


def _resolve(path, cwd):
    """An absolute, normalized path for a spelling in a command — relative spellings against `cwd`."""
    p = path.strip()
    m = re.match(r"^/([A-Za-z])/(.*)$", p)
    if m and os.name == "nt":          # Git Bash spells E:/ as /e/
        p = f"{m.group(1).upper()}:/{m.group(2)}"
    if not os.path.isabs(p) and not re.match(r"^[A-Za-z]:", p):
        p = os.path.join(cwd, p)
    return os.path.normpath(os.path.abspath(p))


def _homed(abs_path):
    """True when the file sits directly in a session store, `.claude/p4/sessions/<s8>/vlds/` — this session's or
    another's (a free's pre-finalizer legitimately rewrites an earlier session's entry; a bare spelling that lands in
    a repo root does not)."""
    return pt.homed_dir(os.path.dirname(abs_path), P4_TAIL)


def _first_group(m):
    return next((g for g in m.groups() if g), "")


def write_targets(payload):
    """[(spelled, absolute)] — every store-NAMED file the call is about to write: a Write/Edit file_path, or
    each write-position path in a shell command, resolved against the payload's cwd and any `cd` earlier in
    the same command (that is exactly how a bare spelling goes wrong). Empty when nothing store-named is
    written."""
    tool = str(payload.get("tool_name") or "")
    inp = payload.get("tool_input") or {}
    if not isinstance(inp, dict):
        return []
    cwd = str(payload.get("cwd") or os.getcwd())
    if tool in ("Write", "Edit", "NotebookEdit"):
        fp = str(inp.get("file_path") or "")
        if fp and os.path.basename(fp) in STORE_FILES:
            return [(fp, _resolve(fp, cwd))]
        return []
    if tool not in ("Bash", "PowerShell"):
        return []
    cmd = str(inp.get("command") or "")
    if not any(f in cmd for f in STORE_FILES):
        return []
    events = []
    for m in CD_RE.finditer(cmd):
        events.append((m.start(), "cd", _first_group(m)))
    for rx in WRITE_RES:
        for m in rx.finditer(cmd):
            events.append((m.start(), "write", _first_group(m)))
    for m in COPY_RE.finditer(cmd):
        args = [a for a in re.findall(r"\"[^\"\n]*\"|'[^'\n]*'|\S+", m.group(1)) if not a.startswith("-")]
        if len(args) >= 2:
            dest = args[-1].strip("\"'")
            if os.path.basename(dest) in STORE_FILES:
                events.append((m.start(), "write", dest))
    out, seen = [], set()
    for _off, kind, value in sorted(events, key=lambda e: e[0]):
        if kind == "cd":
            cwd = _resolve(value, cwd)
            continue
        if not value or os.path.basename(value) not in STORE_FILES:
            continue
        a = _resolve(value, cwd)
        key = os.path.normcase(a)
        if key not in seen:
            seen.add(key)
            out.append((value, a))
    return out


def stray_targets(payload):
    """The subset of write_targets() that lands outside every `.claude/p4/sessions/<s8>/vlds/` directory."""
    return [(s, a) for s, a in write_targets(payload) if not _homed(a)]


def written_text(payload):
    """The text a call persists: a Write's content, an Edit's new_string, or — for a shell command — every
    heredoc body, PowerShell here-string, and quoted argument (a `printf '...' >> file` persists too)."""
    tool = str(payload.get("tool_name") or "")
    inp = payload.get("tool_input") or {}
    if not isinstance(inp, dict):
        return ""
    if tool == "Write":
        return str(inp.get("content") or "")
    if tool == "Edit":
        return str(inp.get("new_string") or "")
    if tool in ("Bash", "PowerShell"):
        cmd = str(inp.get("command") or "")
        bodies = [m.group(3) for m in HEREDOC_RE.finditer(cmd)]
        bodies += [m.group(2) for m in PS_HERE_RE.finditer(cmd)]
        bodies += [(m.group(1) or m.group(2) or "").replace("\\n", "\n") for m in SH_QUOTED_RE.finditer(cmd)]
        return "\n".join(bodies)
    return ""


def placeholder_times(text):
    """Every `time:` value in the text that is not a stamp: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`, digits only.
    Exempt: an empty value, a bracketed template (`[YYYY-MM-DD HH:MM]` in a header shape), and a value holding
    a runtime placeholder (`{now:...}`, `$now`, `%H`) — those do not survive as literals, which is R2's own
    allowance. A trailing `# comment` is ignored."""
    bad = []
    for m in TIME_FIELD_RE.finditer(text):
        v = re.sub(r"\s+#.*$", "", m.group(1)).strip().strip("\"'")
        if not v or v.startswith("[") or any(c in v for c in "{$%"):
            continue
        if not TIME_OK_RE.match(v) and v not in bad:
            bad.append(v)
    return bad


FUTURE_SLACK = datetime.timedelta(minutes=1)   # a write that straddles a minute boundary is not a guess


def future_times(text, now):
    """Every well-formed `time:` value in the text that lies LATER than `now` by more than FUTURE_SLACK — a stamp
    guessed ahead of the clock rather than copied from it (one session stamped rows up to fifty minutes past the
    hook stream's `now:`). A date-only value counts when its date is past today's. Same exemptions as
    placeholder_times(); a value that does not parse is that scan's finding, not this one's."""
    bad = []
    limit = now + FUTURE_SLACK
    for m in TIME_FIELD_RE.finditer(text):
        v = re.sub(r"\s+#.*$", "", m.group(1)).strip().strip("\"'")
        if not v or v.startswith("[") or any(c in v for c in "{$%") or not TIME_OK_RE.match(v):
            continue
        clocked = " " in v
        try:
            stamp = datetime.datetime.strptime(v, NOW_FMT if clocked else "%Y-%m-%d")
        except ValueError:
            continue    # well-shaped but impossible (a 13th month) — not a guess ahead, and not this scan's call
        if (stamp > limit if clocked else stamp.date() > now.date()) and v not in bad:
            bad.append(v)
    return bad


# ─── session-open ───────────────────────────────────────────────────────────────────────────────────────

def recall_lists(index_text):
    """(inject, digest, from_index, pool, models) — the lists and the mode under the index's `## recall` section,
    or the defaults: `pool: subagent` (the hot files pooled by the operator subagent, not injected) or
    `pool: inject` (every inject file chunked into the slots); `operator-model:` the open moment's model,
    `pool-model:` the pool's compose, `pool-child-model:` its child readers', `sweep-model:` the sweep's,
    `pool-road:` the pool's road (skeleton, children, single), `operator-moments:` the continuations before a
    fresh launch, `operator-via:` the agent type a session hands every operator moment to (it launches the operator
    and returns a derived understanding) — `models` carries all seven."""
    inject, digest, pool = None, None, None
    models = {"operator": DEFAULT_OPERATOR_MODEL, "pool": DEFAULT_POOL_MODEL, "child": DEFAULT_POOL_CHILD_MODEL,
              "sweep": DEFAULT_SWEEP_MODEL, "moments": DEFAULT_OPERATOR_MOMENTS, "road": DEFAULT_POOL_ROAD,
              "via": DEFAULT_OPERATOR_VIA}
    in_recall = False
    for l in index_text.split("\n"):
        if l.startswith("## "):
            in_recall = l[3:].strip().lower() == "recall"
            continue
        if not in_recall:
            continue
        m = re.match(r"^(inject|digest|pool|pool-road|pool-model|pool-child-model|operator-model|sweep-model|"
                     r"operator-moments|operator-via):\s*(.*)$", l.strip())
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if key == "pool":
            pool = value.lower() if value.lower() in POOL_MODES else None
        elif key == "operator-via":
            models["via"] = value or None
        elif key == "pool-road":
            if value.lower() in POOL_ROADS:
                models["road"] = value.lower()
        elif key == "operator-moments":
            try:
                models["moments"] = max(0, int(value))
            except ValueError:
                pass
        elif key.endswith("-model"):
            if value:
                models["child" if key == "pool-child-model" else key[:-len("-model")]] = value
        else:
            names = [n.strip() for n in value.split(",") if n.strip()]
            if key == "inject":
                inject = names
            else:
                digest = names
    return (inject if inject is not None else DEFAULT_INJECT,
            digest if digest is not None else DEFAULT_DIGEST,
            inject is not None or digest is not None,
            pool or DEFAULT_POOL,
            models)


def pool_session(store):
    """The short id named on store/recall-pool.md's `session:` line, or None."""
    path = os.path.join(store, POOL_FILE)
    if not os.path.exists(path):
        return None
    for l in read_text(path).split("\n"):
        m = re.match(r"^session:\s*([0-9A-Za-z-]+)", l)
        if m:
            return m.group(1)[:8]
    return None


def operator_directive(store, tag, now, models, keyspace=False):
    """The one block the pooled mode injects in place of the hot files: judged operations are the operator
    subagent's and its derivation is what the model acts on; the close is the record script's, mechanical."""
    root = plugin_root()
    brief = os.path.join(root, "hooks", "operator-prompt.md")
    pool = os.path.join(root, "hooks", "pool-prompt.md")
    record = os.path.join(root, "scripts", "record.py")
    normalize = os.path.join(root, "scripts", "normalize.py")
    idb = os.path.join(root, "scripts", "idb.py")
    via = models.get("via")
    sweep = (
        f"and sweep (naming what is cold when the check shows judged debt, on {models['sweep']}; the placement is "
        f"`python {idb} --store <store> pour --session <id> --now <the latest now:> <file>:<head lines>` — any "
        "count pours, the keyspace opens no position). "
    ) if keyspace else (
        "and sweep (naming what is cold when the check shows judged debt — held when the "
        "last sweep's `[gc]` line found no count opening one position and nothing cold has landed since — on "
        f"{models['sweep']}; the placement is `python {normalize} --store <store> --session <id> --pour "
        "<file>:<head lines>`). "
    )
    conducted = (
        f"CONDUCTED — the index's `operator-via:` names {via}: every operator moment goes to it instead (the Agent "
        f"tool, subagent_type {via}, in the foreground), the same one message with one more line — `conductor: launch "
        "the operator with this message on <the moment's model>, and return a derived understanding` — and it "
        "launches the operator on that model, fresh for each moment, and receives its derivation (the operator then "
        "sends nothing to `main`); what comes back to you is its DERIVED UNDERSTANDING — the barrier, the intent, the "
        "standing rules that bear on the task by label (the rules themselves arrive whole in their own SessionStart "
        "block), what the store establishes for the task and how firmly — which you act on as you would the "
        "derivation, never a response to the owner: the response stays yours. Continue the conductor, not the "
        f"operator, for later moments; when {via} is not among your agent types, launch the operator directly and "
        "say so.\n"
    ) if via else ""
    return (
        "### recall, and every store operation — the operator subagent, never this context\n"
        "The hot files are not in this context, and no store file is read or written here. Two instruments carry "
        "the work. The OPERATOR — the Agent tool, subagent_type general-purpose, in the foreground — for what needs "
        f"judgment: open (the pool at the first prompt, by the index's road, {models['road']} (skeleton: "
        f"`phi.py pool` writes the skeleton from the barrier's own lines and the operator makes one judged pass on "
        f"{models['pool']}, no model reading a file; children: the same skeleton with one reader per file on "
        f"{models['child']}, launched by the operator in the background to pick what bears on the task, the picks "
        f"folded in by the script, composed on {models['pool']} — the operator launched in the background then, "
        "its progress lines arriving as its messages and its derivation with its completion; single: the operator "
        f"alone on {models['pool']}) — the session speaks to the operator, the operator to its children; the barrier "
        f"when the prompt hook names a candidate row, and the intent of an unknown short message, on "
        f"{models['operator']}) " + sweep + "Send it one message:\n"
        f"  Read {brief} and do what it says. store: {store} | session: {tag} | now: <the latest now:> | "
        "moment: open or sweep | <the facts only this context holds>\n"
        f"{conducted}"
        "Launch it once per session; continue it for later moments with SendMessage (to: the launch result's agent "
        f"id; message: the moment, the latest now:, the facts) — at most {models['moments']} continuations, then "
        "launch fresh, and fresh whenever a continuation fails; its derivation is what you act on — listed in one line "
        "at the top of the reply, and once the reply's final plan is settled, before its first act, one fence with no "
        "shell tag lists that plan as a short-form bulleted prose summary — both process text, carrying no "
        "deliverable: every fence, every copyable block and the answer itself go in the FINAL message, after the "
        "turn's last tool call, since the Code tab does not reliably show what sits before the closing tool calls; "
        "the popup is that last call, and the final message names what it asks. The CLOSE — every "
        "turn, before the final message — is mechanical: write the turn's record to the notebook (one `## <file>` block per "
        "entry in the file's own shape; a dispatch row by its fingerprint's opening plus the fields to add) and run "
        f"`python {record} --store {store} --session <id> --now <the latest now:> --record <path>`; its derivation "
        "is what you report. A known short command needs no operator: the prompt hook derives it from the store's own "
        f"adoption tokens. The pool per {pool} is the recall, every item still through the gc read barrier; the "
        f"operator writes store/{POOL_FILE}, which a compact re-injects. When a derivation is not enough to steer, "
        "ask the operator for the entry, never open the file here. No Agent tool in this session → the degraded "
        "path: do the operation here and say so. The index's ## recall section rules it: `pool: inject` restores "
        "the slot injection of every inject file; `operator-model:`, `pool-model:`, `pool-child-model:`, "
        "`sweep-model:` pick the models; `pool-road:` the pool's road (skeleton, children, single); "
        "`operator-moments:` the continuations before a fresh launch; `operator-via:` an agent that conducts the "
        "operator for you and returns a derived understanding."
    )


def known_short(store, preview):
    """(count, prior) — how often the store's owner corpus holds this exact short message, and the last dispatch
    row that carried it with what was done: the mechanical derivation of a known command, so no operator is
    launched for 'commit' or 'push it'. (0, None) when the message is not a known command."""
    token = _token(preview)
    if not token:
        return 0, None
    count = sum(1 for t in voice_corpus(store) if _token(t) == token)
    if count < KNOWN_SHORT_MIN:
        return 0, None
    prior = None
    for p in session_dispatch_records(store):
        if not os.path.exists(p):
            continue
        _header, blocks = split_entries(read_text(p))
        for b in blocks:
            if not b.startswith("- fingerprint:"):
                continue
            fp = _field_value(b.split("\n", 1)[0][len("- fingerprint:"):])
            if _token(fp) != token:
                continue
            m = re.search(r"^  addressed:[ \t]*(.*?)[ \t]*$", b, re.M)
            if m and m.group(1):
                prior = m.group(1)
    return count, prior


def index_digest(index_text, register=True):
    """The index in a few lines: the register (the φ-register's only), one line of hot rows (file live/budget), the
    updated: line."""
    out = []
    if register:
        m = re.search(r"^register:\s*(\S*)", index_text, re.M)
        out.append(f"register: {m.group(1) if m else '(none)'}")
    section, hot = None, []
    for l in index_text.split("\n"):
        if l.startswith("## "):
            section = l[3:].strip()
            continue
        if section == "hot" and l.startswith("|") and not set(l.replace("|", "").strip()) <= {"-", " ", ":"}:
            cells = [c.strip() for c in l.strip("|").split("|")]
            if cells and cells[0] != "file" and len(cells) > 4:
                hot.append(f"{cells[0]} {cells[1]}/{cells[4]}")
        if l.startswith("updated:"):
            out.append(l)
    if hot:
        out.insert(1 if register else 0, "hot (live/budget): " + ", ".join(hot))
    return "\n".join(out)


def digest_line(store, fname):
    """One line for a read-list file — inside the p4 layout, across every session store a read of it covers (this
    session's alone for a session-local file)."""
    found = pt.paths(store, fname)
    if not found:
        return f"- {fname} — absent"
    entries, size = [], 0
    for path, _lb in found:
        entries += entry_lines(read_text(path))
        size += os.path.getsize(path)
    last = entries[-1][:100] if entries else "(no entries)"
    where = ""
    if pt.partitioned(store):
        where = (" in this session" if fname in pt.SESSION_LOCAL
                 else f" across {len(found)} session{'' if len(found) == 1 else 's'}")
    return f"- {fname} — {len(entries)} entries{where}, {size:,} B; last: {last}"


def session_source(payload):
    return str(payload.get("source") or payload.get("mode") or "startup")


def split_entries(text):
    """(header, [entry blocks]) — the header runs up to and including the first column-0 '---' line; entry
    blocks are column-0 '- ' lines with their continuation lines, in order; prose before the first entry rides
    as the first block, prose after the last entry with the last."""
    lines = text.split("\n")
    try:
        sep = lines.index("---")
    except ValueError:
        sep = -1
    header = "\n".join(lines[:sep + 1]) if sep >= 0 else ""
    blocks, cur = [], []
    for l in lines[sep + 1:]:
        if l.startswith("- ") and cur:
            blocks.append("\n".join(cur))
            cur = []
        cur.append(l)
    if cur:
        blocks.append("\n".join(cur))
    return header, blocks


def chunk_plan(store, inject):
    """[(fname, part, parts, text)] — every inject file split at entry boundaries into chunks that fit a slot.
    Deterministic from the files alone, so every slot process computes the same plan."""
    plan = []
    for fname in inject:
        path = os.path.join(store, fname)
        if not os.path.exists(path):
            plan.append((fname, 1, 1, None))
            continue
        header, blocks = split_entries(read_text(path).rstrip("\n"))
        chunks, cur = [], header
        for b in blocks:
            cand = (cur + "\n" + b) if cur else b
            if len(cand) > SLOT_BUDGET - SLOT_HEAD and cur:
                chunks.append(cur)
                cur = b
            else:
                cur = cand
        if cur or not chunks:
            chunks.append(cur)
        for i, c in enumerate(chunks, 1):
            plan.append((fname, i, len(chunks), c))
    return plan


def plan_label(item):
    fname, part, parts, _text = item
    return fname if parts == 1 else f"{fname} (part {part}/{parts})"


def cmd_session_standing(payload, store, part):
    """The owner's standing rules, whole, in an output of their own — every LIVE form ruling and every-turn index
    rule, uncut, as `phi.py standing` prints them — so a session holds them whatever the pool's cap cuts and
    whichever road the recall takes. The pooled mode only, since the inject mode's slots carry the files whole
    already; every source prints it, because a resumed or compacted conversation may predate the block or have
    summarized it away."""
    index_path = pt.config_index(store)
    if not os.path.exists(index_path) and store_engine(store)[0] != "idb":
        return 0
    _inject, _digest, _from_index, pool, _models = recall_lists(read_text(index_path) if os.path.exists(index_path)
                                                                else "")
    if pool != "subagent":
        return 0
    phi = os.path.join(plugin_root(), "scripts", "phi.py")
    if not os.path.exists(phi):
        return 0
    sid, _label, _title = session_tag(payload, store)
    try:
        r = subprocess.run([sys.executable or "python3", phi, "--store", store, "standing", "--session", sid[:8],
                            "--part", str(part)], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        if part == 0:
            print(f"### standing rules — not printed: phi.py standing could not run ({e})")
        return 0
    out = r.stdout.decode("utf-8", "replace").replace("\r\n", "\n").strip()
    if out:
        print(out)
    return 0


def cmd_session_slot(payload, store, slot):
    """One chunk per hook output — the only way past the per-hook cap; silent in the pooled mode."""
    if session_source(payload) in HELD_SOURCES:
        return 0
    index_path = pt.config_index(store)
    if not os.path.exists(index_path):
        return 0
    inject, _digest, _from_index, pool, _models = recall_lists(read_text(index_path))
    if pool != "inject":
        return 0
    plan = chunk_plan(store, inject)
    if slot >= len(plan):
        return 0
    item = plan[slot]
    fname, _part, _parts, text = item
    head = f"### {plan_label(item)} — recall slot {slot} (SessionStart hook; every item still passes the gc read barrier)"
    print(head)
    if text is None:
        print("(absent)")
    elif len(head) + len(text) + 2 > SLOT_BUDGET:
        print(f"NOT injected: this part alone is {len(text):,} characters, over the harness's {HOOK_OUTPUT_CAP:,}-"
              f"character hook-output cap — read it by hand before anything in it steers")
        print(digest_line(store, fname))
    else:
        print(text)
    return 0


# ─── the owner-voice digest ─────────────────────────────────────────────────────────────────────────────

FIELD_RE = re.compile(r"^[ \t]*(?:- )?(owner-words|fingerprint|by):[ \t]*(.*?)[ \t]*$", re.M)


def _field_value(raw):
    v = raw.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v.strip()


def _token(text):
    t = text.lower().replace("…", " ").replace("\u2019", "'")
    t = re.sub(r"[^\w\s'/-]", " ", t)
    return " ".join(t.split())


def voice_corpus(store):
    """Every verbatim owner field across the session stores: owner-words and by in local-storage.md and
    tombstones.md, fingerprint in every session's dispatch.md. Header template lines ([...] values) are skipped."""
    texts = []
    paths = [p for f in ("local-storage.md", "tombstones.md") for p, _lb in pt.paths(store, f)]
    paths += session_dispatch_records(store)
    for p in paths:
        if not os.path.exists(p):
            continue
        for m in FIELD_RE.finditer(read_text(p)):
            v = _field_value(m.group(2))
            if v and not v.startswith("["):
                texts.append(v)
    return texts


def voice_rulings(store):
    """[(time, form, owner-words)] for every local-storage ruling that carries a `form:` field or whose
    owner-words name a delivery form — in file order, so the tail is the latest."""
    path = os.path.join(store, "local-storage.md")
    if not os.path.exists(path):
        return []
    _header, blocks = split_entries(read_text(path))
    out = []
    for b in blocks:
        if not b.startswith("- "):
            continue
        fields = {}
        for l in b.split("\n"):
            mm = re.match(r"^(?:- |  )([a-z-]+):[ \t]*(.*?)[ \t]*$", l)
            if mm and mm.group(1) not in fields:
                fields[mm.group(1)] = mm.group(2)
        words = _field_value(fields.get("owner-words", ""))
        form = _field_value(fields.get("form", ""))
        if not words or words.startswith("["):
            continue
        low = words.lower()
        if form or any(w in low for w in VOICE_FORM_WORDS):
            out.append((fields.get("time", "").strip(), form, words))
    return out


def owner_voice(store):
    """The `### owner voice` block: a mechanical digest of the store's verbatim owner fields — median message
    length, the most frequent short messages (adoption tokens), and the latest delivery-form rulings. No
    judgment here; the model derives a short, typo'd, or truncated message's intent from it before asking."""
    texts = voice_corpus(store)
    if not texts:
        return None
    lengths = sorted(len(t) for t in texts)
    median = lengths[len(lengths) // 2]
    tokens = Counter(_token(t) for t in texts if 0 < len(_token(t).split()) <= VOICE_TOKEN_WORDS)
    top = tokens.most_common(VOICE_TOKENS)
    rulings = voice_rulings(store)[-VOICE_RULINGS:]
    lines = [f"### owner voice (mechanical digest of {len(texts)} verbatim owner fields — derive a short, typo'd, "
             f"or truncated message's intent from these before asking)",
             f"- median message length: {median} characters"]
    if top:
        lines.append(f"- adoption tokens (most frequent messages of at most {VOICE_TOKEN_WORDS} words): "
                     + ", ".join(f'"{t}" ×{c}' for t, c in top))
    if rulings:
        lines.append(f"- delivery-form rulings, latest {len(rulings)} (form: {' | '.join(VOICE_FORM_WORDS)}):")
        for t, form, words in rulings:
            w = words if len(words) <= 160 else words[:159] + "…"
            lines.append(f'  - {t or "(undated)"} form={form or "(named in the words)"}: "{w}"')
    out = "\n".join(lines)
    if len(out) > VOICE_CAP:
        out = out[:VOICE_CAP].rsplit("\n", 1)[0] + "\n  (digest cut at the cap)"
    return out


def cmd_session_open(payload, store):
    source = session_source(payload)
    held = source in HELD_SOURCES
    now = datetime.datetime.now()
    sid, tag, title = session_tag(payload, store)
    print(f"## VLDS recall (SessionStart hook, source={source}, session {tag}) — every item still passes the gc "
          f"read barrier: freed, stale, or unowned → surface it, do not apply it")
    print(now_line(now))
    if sid != "unknown":
        seed_session_store(store)   # the session's own dispatch.md and briefs.md, before the check below reads them
    if held:
        if sid != "unknown":
            fresh = record_seen(store, sid, now, title)
            print(f"{source}: session {tag} {'recorded as seen' if fresh else 'already seen'} — its next prompt "
                  f"pours nothing; the conversation holds its own recall, so digest and verdict only")
    engine, _setting, _state = store_engine(store)
    keyspace = engine == "idb"
    index_path = pt.config_index(store)
    if not os.path.exists(index_path) and not keyspace:
        print("no phi-index.md yet — cold-start: read store/* yourself, then bootstrap the register per /vlds:gc")
        return 0
    index_text = read_text(index_path) if os.path.exists(index_path) else ""
    if not index_text:
        print("no phi-index.md yet — the keyspace writes it at the first turn close; until then the hooks' defaults "
              "apply")
    inject, digest, from_index, pool, models = recall_lists(index_text)
    via_note = f"; via {models['via']}" if models.get("via") else ""
    model_note = (f" (operator {models['operator']}, pool {models['pool']}, children {models['child']}, "
                  f"sweep {models['sweep']}; road {models['road']}; {models['moments']} continuations{via_note})"
                  if pool == "subagent" else "")
    print(f"lists from {'the index’s ## recall section' if from_index else 'the hook defaults (the index has no ## recall section)'}"
          f" — pool: {pool}{model_note}; "
          f"{'read' if pool == 'subagent' else 'inject'}: {', '.join(inject)}; digest: {', '.join(digest)}")
    if held:
        for fname in inject + digest:
            print(digest_line(store, fname))
        if source == "compact" and pool == "subagent":
            owner = pool_session(store)
            pool_path = os.path.join(store, POOL_FILE)
            if owner and owner == sid[:8]:
                text = read_text(pool_path).rstrip("\n")
                print(f"\n### {POOL_FILE} — this session's pooled recall, re-injected after the compact")
                if len(text) > SLOT_BUDGET:
                    print(f"NOT re-injected: {len(text):,} characters, over the hook-output cap — read store/{POOL_FILE} "
                          "by hand before anything in it steers")
                else:
                    print(text)
                m = idb_module() if keyspace else None
                if m is not None:
                    try:
                        print(m.pool_diff(store))
                    except Exception as e:  # noqa: BLE001
                        print(f"pool: its freshness could not be told ({type(e).__name__})")
            elif owner:
                print(f"- {POOL_FILE} belongs to session {owner}, not this one — re-pool per the SessionStart directive "
                      "if the compact took the recall with it")
    elif pool == "subagent":
        print()
        print(operator_directive(store, tag, now, models, keyspace))
        m = idb_module()
        if keyspace and m is not None:
            print("\n### keyspace — digest (idb/keys.tsv; the subagent reads phi-index.md whole)")
            print(m.keyspace_digest(store))
            own = os.path.join(store, "phi-index.md")
            own_text = read_text(own) if os.path.exists(own) else ("" if pt.partitioned(store) else index_text)
            if own_text:
                print(index_digest(own_text, register=False))
            if pt.partitioned(store):
                print(f"store: {session_store_label(store)} — this session's own; the recall config is "
                      ".claude/p4/vindex/phi-index.md, and the read list spans every session's store")
        else:
            print("\n### phi-index.md — digest (the subagent reads it whole)")
            print(index_digest(index_text))
            line = m.phi_engine_line(store) if m is not None else ""
            if line:
                print(line)
        print("\n### read list — digest lines (the subagent reads each whole; open one by hand only when an entry there is about to steer)")
        for fname in inject + digest:
            print(digest_line(store, fname))
        voice = owner_voice(store)
        if voice:
            print()
            print(voice)
    else:
        print("\n### phi-index.md")
        print(index_text.rstrip("\n"))
        m = idb_module() if not keyspace else None
        line = m.phi_engine_line(store) if m is not None else ""
        if line:
            print(line)
        plan = chunk_plan(store, inject)
        print(f"\n### inject — each chunk arrives as its own hook output (slots 0..{SLOTS - 1}), split at entry "
              f"boundaries under the harness's {HOOK_OUTPUT_CAP:,}-character cap")
        for i, item in enumerate(plan[:SLOTS]):
            print(f"- slot {i}: {plan_label(item)}")
        if len(plan) > SLOTS:
            print(f"- beyond the registered slots, NOT injected: "
                  f"{', '.join(plan_label(it) for it in plan[SLOTS:])} — read by hand before it steers")
        print("\n### digest — read on demand, when an entry there is about to steer")
        for fname in digest:
            print(digest_line(store, fname))
        voice = owner_voice(store)
        if voice:
            print()
            print(voice)
    print("\n### idb.py check" if keyspace else "\n### phi.py check")
    print(check_summary(store))
    return 0


# ─── prompt-open ────────────────────────────────────────────────────────────────────────────────────────

def lock_holder(store, sid, keyspace=False):
    """The other session holding a fresh sweep lock, or None — idb/.sweep-lock on the keyspace, arc/'s otherwise."""
    lock = os.path.join(store, "idb" if keyspace else "arc", ".sweep-lock")
    if not os.path.exists(lock):
        return None
    holder = (read_text(lock).split() or ["?"])[0]
    age = datetime.datetime.now().timestamp() - os.path.getmtime(lock)
    if holder != sid and age < LOCK_STALE_S:
        return f"{holder} ({int(age)} s old)"
    return None


NOTIFICATION_PREFIX = "<task-notification>"   # a background task's completion, delivered as a prompt
AGENT_MESSAGE_PREFIX = "<agent-message "        # a report from one of the session's own agents — the operator's stream lines among them
NOTIFICATION_ADDRESSED = ("a task notification — consumed by the session's next reply; no ask to answer, nothing "
                          "for the operator")
AGENT_MESSAGE_ADDRESSED = ("an agent's message — a report from the session's own subagent, consumed by the next reply; "
                           "no ask to answer, nothing for the operator")


def stamp(store, prompt, tag, now, state=None, arrival="turn", addressed=None, fields=None):
    path = os.path.join(store, "dispatch.md")
    if not os.path.exists(path):
        return None
    fp = " ".join(str(prompt).split())
    if len(fp) > FINGERPRINT_CHARS:
        fp = fp[:FINGERPRINT_CHARS - 1] + "…"
    fp = fp.replace('"', "'")
    nl = "\r\n" if b"\r\n" in read_bytes(path)[:4096] else "\n"
    entry = (f'{nl}- fingerprint: "{fp}"{nl}'
             f"  time: {now:{NOW_FMT}}{nl}"
             f"  arrival: {arrival} (stamped by the prompt hook, session {tag}){nl}")
    for k, v in (fields or {}).items():
        entry += f"  {k}: {v}{nl}"
    if state:
        entry += f"  state: {state}{nl}"
    if addressed:
        entry += f"  addressed: {addressed}{nl}"
    with open(path, "ab") as f:
        f.write(entry.encode("utf-8"))
    return fp


def barrier_rows(store, preview):
    """[(fingerprint, addressed)] for the earlier rows barrier_candidates names — `addressed` True when the row
    carries an addressed: field, which is what makes a picker's later submit FRESH by construction."""
    path = os.path.join(store, "dispatch.md")
    if not os.path.exists(path):
        return []
    new = set(_token(preview).split())
    if not new:
        return []
    out, cur = [], None
    for l in read_text(path).split("\n"):
        m = re.match(r'^- fingerprint:\s*"?(.*?)"?\s*$', l)
        if m:
            old = set(_token(m.group(1)).split())
            hit = bool(old) and (old == new or (len(new) >= BARRIER_MIN_TOKENS
                                                and len(old & new) / len(old | new) >= BARRIER_JACCARD))
            cur = [m.group(1)[:60], False] if hit else None
            if cur:
                out.append(cur)
        elif cur is not None and l.startswith("  addressed:") and l.split(":", 1)[1].strip():
            cur[1] = True
    return [(fp, done) for fp, done in out]


def picker_shape(preview):
    """('submit', title, question_riding) for the elicitation shell's submit line, ('skip', None, False) for its
    skip, None for anything else. A `?` inside the submitted values is a detail-ask riding on a ruling."""
    m = SUBMIT_RE.match(preview)
    if m:
        return ("submit", m.group(1).strip(), "?" in m.group(2))
    m = ACTS_MARK_RE.search(preview)
    if m:
        t = ACTS_TITLE_RE.search(preview)
        title = t.group(1).strip() if t else f"acts page round {m.group(1)}"
        return ("submit", title, any("?" in n for n in ACTS_NOTE_RE.findall(preview)))
    if SKIP_RE.match(preview):
        return ("skip", None, False)
    return None


def last_picker(payload, preview):
    """('widget' | 'panel', title) when a picker was the last act of the transcript's last assistant turn — a
    show_widget or AskUserQuestion call with no later tool call and no later user prompt but the current one
    (which may or may not be recorded yet at hook time) — else None."""
    path = payload.get("transcript_path")
    if not path or not os.path.exists(str(path)):
        return None
    picker, prompts_after = None, 0
    try:
        with open(str(path), encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"tool_use"' not in line and '"user"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                msg = rec.get("message") if isinstance(rec, dict) else None
                if not isinstance(msg, dict):
                    continue
                role, content = msg.get("role"), msg.get("content")
                if role == "assistant" and isinstance(content, list):
                    for b in content:
                        if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                            continue
                        name = str(b.get("name") or "")
                        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                        if not PICKER_TOOL_RE.match(name):
                            picker = None          # a later act: the picker was not the turn's close
                            continue
                        if name == "AskUserQuestion":
                            qs = inp.get("questions") or []
                            q0 = qs[0] if qs and isinstance(qs[0], dict) else {}
                            title = q0.get("header") or q0.get("question") or ""
                            picker = ("panel", " ".join(str(title).split())[:80])
                        else:
                            picker = ("widget", " ".join(str(inp.get("title") or "").split())[:80])
                        prompts_after = 0
                elif role == "user" and picker is not None:
                    text = content if isinstance(content, str) else None
                    if text is None and isinstance(content, list) and content and \
                            all(isinstance(x, dict) and x.get("type") == "text" for x in content):
                        text = " ".join(str(x.get("text") or "") for x in content)
                    if text is None:
                        continue               # a tool_result
                    t = " ".join(text.split())
                    if not t or t.startswith("<") or t == preview:
                        continue               # a system reminder, a notification, or the prompt being stamped
                    prompts_after += 1
    except OSError:
        return None
    return picker if picker is not None and prompts_after == 0 else None


def standing_labels(store):
    """The labels briefs.md holds as standing — an entry whose `standing:` carries a time — with their counts."""
    found = pt.paths(store, BRIEFS_FILE)
    if not found:
        return {}
    counts, ruled, label, standing = {}, set(), None, False
    body = [l for path, _lb in found for l in entry_body_lines(read_text(path)) + ["- end:"]]
    for l in body + ["- end:"]:
        if l.startswith("- "):
            if label:
                counts[label] = counts.get(label, 0) + 1
                if standing:
                    ruled.add(label)
            label, standing = None, False
        elif l.startswith("  omitted:"):
            v = l.split(":", 1)[1].strip()
            label = _field_value(v).split()[0].strip(",;").lower() if v else None
        elif l.startswith("  standing:"):
            standing = bool(re.match(r"20\d\d-\d\d-\d\d", l.split(":", 1)[1].strip()))
    return {k: counts[k] for k in sorted(ruled)}


def entry_body_lines(text):
    """The lines after the header separator — the entries, never the header's own shape template."""
    lines = text.replace("\r\n", "\n").split("\n")
    try:
        return lines[lines.index("---") + 1:]
    except ValueError:
        return lines


def ensure_dispatch_shape(store):
    """Add `kind:` and `on:` to a dispatch.md header written before the detail-ask recorder existed — the header
    is the shape's authority, the pour reseeds from it, and a row carrying a field the header lacks is drift."""
    path = os.path.join(store, "dispatch.md")
    if not os.path.exists(path):
        return False
    data = read_bytes(path)
    parts = split_header(data)
    if not parts:
        return False
    header, sep, body = parts
    if b"\n  kind:" in header or b"\n  arrival:" not in header:
        return False
    nl = b"\r\n" if b"\r\n" in header else b"\n"
    lines = header.split(nl)
    for i, l in enumerate(lines):
        if l.startswith(b"  arrival:"):
            lines[i:i + 1] = [l,
                              "  kind: [detail-ask | submit+detail-ask — the prompt hook's, when a question about a "
                              "served picker arrives; absent otherwise]".encode("utf-8"),
                              "  on: [the picker it asks about — widget «title» | panel «header»; absent "
                              "otherwise]".encode("utf-8")]
            break
    else:
        return False
    write_bytes(path, nl.join(lines) + sep + body)
    return True


def take_turn_close_reports(store, sid):
    """This session's lines from store/.turn-close, removed as they are taken — the Stop hook wrote them, and
    the prompt that follows is where the model and the user learn what the light sweep did."""
    path = os.path.join(store, TURN_CLOSE)
    if not os.path.exists(path):
        return []
    mine, others = [], []
    for l in read_text(path).split("\n"):
        if not l.strip():
            continue
        parts = l.split(" ", 3)
        (mine if parts[0] == sid else others).append(l)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(others) + ("\n" if others else ""))
    out = []
    for l in mine:
        parts = l.split(" ", 3)
        if len(parts) > 3:
            out.append(f"- turn-close ({parts[2]}): {parts[3]}")
    return out


def cmd_prompt_open(payload, store):
    prompt = payload.get("prompt") or payload.get("user_input") or ""
    if not str(prompt).strip():
        return 0
    sid, tag, title = session_tag(payload, store)
    now = datetime.datetime.now()
    os.makedirs(store, exist_ok=True)
    lines = [f"## VLDS prompt hook (session {tag})", "- " + now_line(now)]
    if not title:
        lines.append("- title: none yet — no custom-title record in the transcript at hook time (it is written "
                     "asynchronously) and none recorded in .sessions; re-read at the next prompt")
    lines += take_turn_close_reports(store, sid)
    seed_session_store(store)
    if record_seen(store, sid, now, title):
        lines.append(f"- session store: {session_store_label(store)} — this session's own directory holds every entry "
                     "it writes; nothing is poured or dated")
        index_path = pt.config_index(store)
        index_txt = read_text(index_path) if os.path.exists(index_path) else (
            "" if store_engine(store)[0] == "idb" else None)
        if index_txt is not None and recall_lists(index_txt)[3] == "subagent":
            lines.append("- operator (open) owed now: the pool — not yet pooled for this session; derive this first "
                         "prompt's task in one line and launch the operator before answering, per the SessionStart "
                         "directive (the Agent tool, the brief at hooks/operator-prompt.md, the pool's model); its "
                         "derivation carries the recall; once the reply's final plan is settled, before its first act, one "
                         "untagged fence lists that plan as short bullets")
    preview = " ".join(str(prompt).split())
    if preview.startswith(NOTIFICATION_PREFIX) or preview.startswith(AGENT_MESSAGE_PREFIX):
        # a background task's completion is not an ask, and neither is a message from the session's own agent (the
        # operator's stream lines, one per child): the barrier has no question to put, and a row left open here
        # would be closed by an operator whose own completion arrives the same way — a loop; the row is the hook's
        # whole, stamped complete on arrival
        notice = preview.startswith(NOTIFICATION_PREFIX)
        fp = stamp(store, prompt, tag, now, state="FRESH", arrival="task notification" if notice else "agent message",
                   addressed=NOTIFICATION_ADDRESSED if notice else AGENT_MESSAGE_ADDRESSED)
        if fp is not None:
            lines.append(f'- stamped: dispatch.md row "{fp[:80]}" at {now:{NOW_FMT}} — '
                         f"{'a task notification' if notice else 'an agent message'}: its row is complete on arrival "
                         "(FRESH, consumed); nothing for the operator")
        print("\n".join(lines))
        return 0
    words = len(preview.split())
    known, prior = known_short(store, preview) if words <= SHORT_WORDS else (0, None)
    # a known short command is a repeated act by nature — the owner's own adoption token — never an echo: the
    # barrier has no question to put, and its intent is the store's to give
    rows = [] if known else barrier_rows(store, preview)
    cands = [fp_ for fp_, _done in rows]
    # the detail-ask recorder: a picker was the last act of the last assistant turn, and this prompt is neither
    # the elicitation shell's submit line nor its skip — a question about the picker, which the close names in
    # briefs.md; a submit whose textbox carries a question is the third case, a ruling with a detail-ask riding
    shape = picker_shape(preview)
    picker = last_picker(payload, preview)
    fields = {}
    if shape is not None:
        kind, title, riding = shape
        if riding:
            fields = {"kind": "submit+detail-ask", "on": f"widget «{title}»"}
    elif picker is not None:
        fields = {"kind": "detail-ask", "on": f"{picker[0]} «{picker[1]}»"}
    if fields and ensure_dispatch_shape(store):
        lines.append("- dispatch.md header: `kind:` and `on:` added to the row shape (the detail-ask recorder's fields)")
    # a picker's submit or skip resembling an earlier row: served fresh after that row was addressed, it is FRESH
    # by construction (the owner's ruling of 2026-09-22) — the hook writes FRESH when every resembling row is
    # addressed; an open one leaves the call to this context, never the operator
    fresh_by_construction = bool(shape) and bool(rows) and all(done for _fp, done in rows)
    state = "FRESH" if (not cands or fresh_by_construction) else None
    fp = stamp(store, prompt, tag, now, state=state, fields=fields)
    if fp is None:
        lines.append("- stamp: dispatch.md absent — the row is the operator's to append")
    elif cands and fresh_by_construction:
        lines.append(f'- stamped: dispatch.md row "{fp[:80]}" at {now:{NOW_FMT}} — barrier: it resembles '
                     f'{len(cands)} earlier row{"s" if len(cands) > 1 else ""} (latest: "{cands[-1]}"), every one '
                     "addressed — a picker's submit served after them is FRESH by construction; state: FRESH written, "
                     "nothing for the operator")
    elif cands and shape is not None:
        lines.append(f'- stamped: dispatch.md row "{fp[:80]}" at {now:{NOW_FMT}} — barrier: it resembles '
                     f'{len(cands)} earlier row{"s" if len(cands) > 1 else ""} (latest: "{cands[-1]}"), at least one '
                     "still open — a picker's submit is judged HERE, in one line, never by the operator: FRESH "
                     "unless it re-submits the very picker the open row came from; complete the row at the close")
    elif cands:
        lines.append(f'- stamped: dispatch.md row "{fp[:80]}" at {now:{NOW_FMT}} — barrier: it resembles '
                     f'{len(cands)} earlier row{"s" if len(cands) > 1 else ""} (latest: "{cands[-1]}"); state: left '
                     "open — hand the message to the operator (open) before answering; its derivation says FRESH, "
                     "ECHO, or SUPERSEDED, and the operator completes the row")
    else:
        lines.append(f'- stamped: dispatch.md row "{fp[:80]}" at {now:{NOW_FMT}} — barrier: no earlier row '
                     "resembles it; state: FRESH written; addressed: is the record's at the turn's close")
    if fp is not None and fields:
        on = fields["on"]
        what = ("a question riding on the submit's textbox" if fields["kind"] == "submit+detail-ask"
                else "a question about the picker, not its submit")
        lines.append(f"- detail-ask on {on}: {what} — answer it, and the close owes store/briefs.md an entry: "
                     "`asked:` verbatim, `on:` as stamped, `at:` closing or fork, `omitted:` the class the picker's "
                     "briefs left out, as one label; the second instance of a class → the closing picker offers to "
                     "make that label standing")
    standing = standing_labels(store)
    if standing:
        lines.append("- standing brief lines: " + ", ".join(f"`{k}:` (×{v})" for k, v in sorted(standing.items()))
                     + " — every option of a picker carries one line per label; the pre-ask gate bounces a picker "
                     "missing one, once")
    if fp is not None and words <= SHORT_WORDS:
        if known:
            lines.append(f"- short message, known: \"{preview[:40]}\" ×{known} in this store's owner corpus — derive "
                         "it as before, no operator" + (f"; the last time it was addressed: {prior[:160]}" if prior
                                                         else "; no earlier row records what was done"))
        else:
            lines.append(f"- short message ({words} word{'s' if words != 1 else ''}), not a known command: the "
                         "operator (open) derives its intent from the store before you answer; state the derivation "
                         "in one line at the top of the reply, then — the final plan settled, before the first act — one "
                         "untagged fence with the plan as short bullets")
    print("\n".join(lines))
    return 0


# ─── pre-write ──────────────────────────────────────────────────────────────────────────────────────────

def cmd_pre_write(payload, store):
    """Ask before a store-named file lands outside every `.claude/p4/sessions/<s8>/vlds/`, before a persisted entry carries a
    placeholder time, and before one carries a time guessed ahead of the clock; silent when the call writes
    nothing store-named."""
    targets = write_targets(payload)
    if not targets:
        return 0
    now = datetime.datetime.now()
    reasons = []
    for _spelled, a in targets:
        if not _homed(a):
            name = os.path.basename(a)
            reasons.append(f"{name} resolves to {a}, outside the store {store}; a store entry belongs at "
                           f"{os.path.join(store, name)} — proceed only if this file is not VLDS state")
    text = written_text(payload)
    for v in placeholder_times(text):
        reasons.append(f"placeholder time `{v}` in a persisted entry — copy the latest `now:` from the hook "
                       f"stream ({now_line(now)})")
    for v in future_times(text, now):
        reasons.append(f"guessed-ahead time `{v}` in a persisted entry — later than the latest `now:` "
                       f"({now_line(now)}) by more than a minute; a stamp is copied from the hook stream, never "
                       f"written ahead of it")
    if not reasons:
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": "; ".join(reasons)}}))
    return 0


# ─── pre-ask ────────────────────────────────────────────────────────────────────────────────────────────

PILL_RE = re.compile(r"<button\b[^>]*\bclass=\"[^\"]*\belicit-pill\b[^\"]*\"[^>]*>(.*?)</button>", re.S | re.I)
DATA_VALUE_RE = re.compile(r"\bdata-value=\"([^\"]*)\"", re.I)
TAG_RE = re.compile(r"<[^>]+>")
META_OPTIONS = ("all of the above", "other", "skip", "none")


def picker_options(payload):
    """[(option, brief_text)] for the picker a PreToolUse payload is about to serve — the widget's `.elicit-pill`
    buttons (data-value, inner text) or the native panel's options (label, description) — and its fingerprint
    source (the widget's title, or the question texts). Meta options (all of the above, other) carry no brief."""
    name = str(payload.get("tool_name") or "")
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    opts, key = [], ""
    if name == "AskUserQuestion":
        for q in inp.get("questions") or []:
            if not isinstance(q, dict):
                continue
            key += " " + str(q.get("question") or "")
            for o in q.get("options") or []:
                if isinstance(o, dict):
                    opts.append((str(o.get("label") or ""), str(o.get("description") or "")))
    elif PICKER_TOOL_RE.match(name):
        key = str(inp.get("title") or "")
        html = str(inp.get("widget_code") or "")
        for m in PILL_RE.finditer(html):
            attrs_start = html.rfind("<button", 0, m.start(1))
            attrs = html[attrs_start:m.start(1)]
            v = DATA_VALUE_RE.search(attrs)
            label = v.group(1) if v else TAG_RE.sub(" ", m.group(1))
            if "data-other" in attrs.lower():
                continue
            opts.append((" ".join(label.split()), " ".join(TAG_RE.sub(" ", m.group(1)).split())))
        opts.extend(acts_page_options(html))
    return opts, " ".join(key.split())


ACTS_STATE_RE = re.compile(r'<script type="application/json" id="acts-state">(.*?)</script>', re.S)


def acts_page_options(html):
    """[(act title, brief_text)] for the open round of an acts page served as a widget (skills/acts-widget) —
    its options are rendered from a JSON block, not .elicit-pill buttons, so the gate reads that block: the
    brief is the act's summary plus one `label: text` line per brief the act carries."""
    m = ACTS_STATE_RE.search(html)
    if not m:
        return []
    try:
        rounds = json.loads(m.group(1)).get("rounds") or []
    except (ValueError, AttributeError):
        return []
    live = rounds[-1] if rounds and isinstance(rounds[-1], dict) and rounds[-1].get("picked") is None else None
    out = []
    for a in (live or {}).get("acts") or []:
        if isinstance(a, dict):
            briefs = a.get("briefs") if isinstance(a.get("briefs"), dict) else {}
            text = " ".join([str(a.get("summary") or "")] + [f"{k}: {v}" for k, v in briefs.items()])
            out.append((" ".join(str(a.get("title") or "").split()), " ".join(text.split())))
    return out


def cmd_pre_ask(payload, store):
    """Bounce a picker whose option briefs lack a standing label — once per picker fingerprint, so the enriched
    re-issue passes — naming the labels and the count that made each standing; silent when nothing is standing,
    when every option carries every label, and on the second call for the same picker. A deny reaches the model
    before the owner sees the picker, which is what the single-submit, served-fresh closing requires."""
    standing = standing_labels(store)
    if not standing:
        return 0
    opts, key = picker_options(payload)
    real = [(o, b) for o, b in opts if o.strip().rstrip(".").lower().split(" (")[0] not in META_OPTIONS]
    if not real:
        return 0
    missing = {}
    for option, brief in real:
        low = brief.lower()
        lacking = [k for k in standing if not re.search(r"(?<![a-z])" + re.escape(k) + r"\s*:", low)]
        if lacking:
            missing[option] = lacking
    if not missing:
        return 0
    fp = sha12((key or json.dumps(opts, sort_keys=True)).encode("utf-8"))
    seen_path = os.path.join(store, PRE_ASK_SEEN)
    seen = set(read_text(seen_path).split()) if os.path.exists(seen_path) else set()
    if fp in seen:
        return 0
    with open(seen_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(fp + "\n")
    labels = ", ".join(f"`{k}:` (standing since its {v}{'nd' if v == 2 else 'th'} instance)" for k, v in sorted(standing.items()))
    where = "; ".join(f"{o[:40]} lacks {', '.join(ls)}" for o, ls in list(missing.items())[:6])
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": (f"VLDS pre-ask: the picker's briefs lack a standing line — {labels}; "
                                     f"{where}. Re-issue it with one `<label>: …` line per option (store/briefs.md "
                                     "names the class each label stands for); the re-issue of this picker passes.")}}))
    return 0


# ─── pre-agent ──────────────────────────────────────────────────────────────────────────────────────────

def _agent_matches(subagent_type, via):
    """True when the Agent call's subagent_type names the conductor — exactly, or by the bare name either side
    of a plugin prefix (`mister:roboto` and `roboto` are one agent to the harness's listing)."""
    a, b = str(subagent_type or "").strip().lower(), str(via or "").strip().lower()
    return bool(a) and (a == b or a.split(":")[-1] == b.split(":")[-1])


def cmd_pre_agent(payload, store):
    """When the index's `operator-via:` names a conductor, bounce an Agent call from the main context that carries
    the operator brief (hooks/operator-prompt.md) to any other agent type, or to the conductor without its
    `conductor:` line — once per call fingerprint, so a re-issue passes (the contract's own exit: a conductor not
    among the session's agent types is launched around, and said so). Silent inside a subagent (`agent_id` is the
    tell): there the conductor itself launches the operator, which is the road this gate keeps open."""
    if str(payload.get("tool_name") or "") not in ("Agent", "Task") or payload.get("agent_id"):
        return 0
    inp = payload.get("tool_input") or {}
    if not isinstance(inp, dict):
        return 0
    prompt = str(inp.get("prompt") or "")
    if "operator-prompt.md" not in prompt:
        return 0
    index_path = pt.config_index(store)
    via = recall_lists(read_text(index_path))[4].get("via") if os.path.exists(index_path) else None
    if not via:
        return 0
    to_conductor = _agent_matches(inp.get("subagent_type"), via)
    if to_conductor and re.search(r"(?m)^\s*conductor:\s*launch the operator\b", prompt):
        return 0
    fp = sha12(("pre-agent\n" + str(inp.get("subagent_type") or "") + "\n" + prompt).encode("utf-8"))
    seen_path = os.path.join(store, PRE_AGENT_SEEN)
    seen = set(read_text(seen_path).split()) if os.path.exists(seen_path) else set()
    if fp in seen:
        return 0
    with open(seen_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(fp + "\n")
    line = "`conductor: launch the operator with this message on <the moment's model>, and return a derived understanding`"
    if to_conductor:
        why = f"the hand-off to {via} lacks its conductor line — add {line} as the message's last line"
    else:
        why = (f"the index's `operator-via:` names {via} as the conductor, and this call launches the operator as "
               f"`{inp.get('subagent_type') or 'general-purpose'}` around it — re-issue it with subagent_type {via}, "
               f"the same message plus {line}")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": (f"VLDS pre-agent: {why}. When {via} is not among this session's agent types, "
                                     "re-issue this call unchanged — the re-issue passes — and say in the reply that "
                                     "the operator was launched directly.")}}))
    return 0


# ─── post-write ─────────────────────────────────────────────────────────────────────────────────────────

def touched_store(payload, store):
    """What the call wrote, when it is the store's business: a file under the store, a store-named file
    anywhere (stray or homed — the same matcher as pre-write), or a shell command that names the store."""
    tool = str(payload.get("tool_name") or "")
    inp = payload.get("tool_input") or {}
    if not isinstance(inp, dict):
        return None
    fp = inp.get("file_path")
    if fp:
        a = os.path.normcase(os.path.abspath(str(fp)))
        s = os.path.normcase(os.path.abspath(store))
        if a.startswith(s + os.sep):
            return os.path.relpath(a, s)
    targets = write_targets(payload)
    if targets:
        strays = [os.path.basename(a) for _s, a in targets if not _homed(a)]
        if strays:
            return f"a store-named file OUTSIDE the store ({', '.join(sorted(set(strays)))})"
        return "a store file, via " + ("a shell command" if tool in ("Bash", "PowerShell") else tool)
    if fp:
        return None
    if tool in ("Bash", "PowerShell"):
        cmd = str(inp.get("command") or "")
        if re.search(r"\.claude[\\/]+p4[\\/]+sessions[\\/]+[^\\/\s]+[\\/]+vlds", cmd):
            return "the store, via a shell command"
    return None


def check_delta(store, sid, summary):
    """The summary when it differs from the last one this session was handed, else its verdict line alone — the
    context the model works in is finite, and the same debt list pasted after every store write spends it."""
    path = os.path.join(store, CHECK_LAST)
    digest = sha12(summary.encode("utf-8"))
    seen = {}
    if os.path.exists(path):
        try:
            seen = json.loads(read_text(path)) or {}
        except ValueError:
            seen = {}
    if seen.get(sid) == digest:
        verdict = next((l for l in summary.split("\n") if l.startswith(("phi.py check", "idb.py check"))),
                       summary.split("\n")[-1])
        return f"{verdict} — unchanged since the last check this session"
    seen[sid] = digest
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(seen))
    return summary


def written_store(payload):
    """The session store a call wrote into, when it is one — a free's pre-finalizer may rewrite an earlier session's
    entry, and that store is the one to check — else None."""
    inp = payload.get("tool_input") or {}
    fp = inp.get("file_path") if isinstance(inp, dict) else None
    cwd = str(payload.get("cwd") or os.getcwd())
    cands = [_resolve(str(fp), cwd)] if fp else [a for _s, a in write_targets(payload)]
    for a in cands:
        if _homed(a) and pt.p4_of(os.path.dirname(a)):
            return os.path.dirname(a)
    return None


def cmd_post_write(payload, store):
    other = written_store(payload)
    if other and os.path.normcase(os.path.abspath(other)) != os.path.normcase(os.path.abspath(store)):
        store = other
    what = touched_store(payload, store)
    if not what or not os.path.isdir(store):
        return 0
    now = datetime.datetime.now()
    sid = str(payload.get("session_id") or "unknown")
    text = f"{now_line(now)}\nVLDS check after the write to {what}:\n{check_delta(store, sid, check_summary(store))}"
    traced = gc_trace_lines(store, sid)
    if traced:
        text += "\n" + "\n".join(traced)
    pool = os.path.join(store, POOL_FILE)
    just_written = os.path.exists(pool) and (what == POOL_FILE or (what.startswith("the store, via") and
                                                                  time.time() - os.path.getmtime(pool) < 15))
    if just_written and store_engine(store)[0] == "idb":
        m = idb_module()
        try:
            if m is not None and not m.pool_stamp_current(store):
                m.cmd_pool_stamp(store, f"{now:{NOW_FMT}}", quiet=True)
        except Exception:  # noqa: BLE001 — the stamp is a convenience; the check above is the hook's work
            pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
    return 0


# ─── turn-close ─────────────────────────────────────────────────────────────────────────────────────────

def phi_light(store, sid, now, timeout=50):
    """The φ-register's light sweep — scripts/normalize.py --light — and its report line, or '' when it cannot run."""
    if not os.path.exists(os.path.join(store, "phi-index.md")):
        return ""
    script = os.path.join(plugin_root(), "scripts", "normalize.py")
    if not os.path.exists(script):
        return ""
    try:
        r = subprocess.run([sys.executable or "python3", script, "--store", store, "--session", sid, "--light",
                            "--now", f"{now:{NOW_FMT}}"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
        out = f"turn-close: could not run normalize.py — {type(e).__name__}: {e}"
    return next((l for l in reversed(out.split("\n")) if l.startswith("turn-close:")), "").strip()


def run_idb(store, args, prefix, timeout=50):
    """scripts/idb.py <args>: (exit code, the last line starting with `prefix` — or, when the script printed none and
    failed, one naming the failure, so a broken engine is reported rather than silent)."""
    script = os.path.join(plugin_root(), "scripts", "idb.py")
    try:
        r = subprocess.run([sys.executable or "python3", script, "--store", store, *args], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        out, rc = (r.stdout or "") + (r.stderr or ""), r.returncode
    except Exception as e:  # noqa: BLE001
        return 1, f"{prefix} could not run idb.py — {type(e).__name__}: {e}"
    line = next((l for l in reversed(out.split("\n")) if l.startswith(prefix)), "").strip()
    if not line and rc != 0:
        last = next((l for l in reversed(out.split("\n")) if l.strip()), "no output")
        line = f"{prefix} idb.py failed (exit {rc}) — {last.strip()[:200]}"
    return rc, line


def phi_fingerprint(store):
    """The φ-register's shape on disk — arc/'s listing with sizes and mtimes, and the index's — all a shadow or a
    migration's preconditions read: while it stands, their last verdict stands."""
    parts = []
    arc = os.path.join(store, "arc")
    for f in sorted(os.listdir(arc)) if os.path.isdir(arc) else []:
        if f != ".sweep-lock":
            st = os.stat(os.path.join(arc, f))
            parts.append(f"{f}:{st.st_size}:{int(st.st_mtime)}")
    idx = os.path.join(store, "phi-index.md")
    if os.path.exists(idx):
        st = os.stat(idx)
        parts.append(f"index:{st.st_size}:{int(st.st_mtime)}")
    return sha12("|".join(parts).encode("utf-8"))


def verdict_stands(store, fname, fingerprint):
    """True when `fname` recorded this fingerprint less than a day ago — the last verdict still stands."""
    path = os.path.join(store, fname)
    if not os.path.exists(path):
        return False
    parts = read_text(path).split()
    return len(parts) >= 2 and parts[0] == fingerprint and time.time() - os.path.getmtime(path) < VERDICT_MAX_AGE_S


def record_verdict(store, fname, fingerprint, line):
    """Record the fingerprint with the verdict's digest; True when the verdict is not the one last recorded."""
    path = os.path.join(store, fname)
    digest = sha12(line.encode("utf-8"))
    old = read_text(path).split() if os.path.exists(path) else []
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{fingerprint} {digest}\n")
    return len(old) < 2 or old[1] != digest


def cmd_turn_close(payload, store):
    """Stop: the engine's pass, its report left for the next prompt hook. On the φ-register the light normalize sweep;
    on the keyspace `idb.py light`; a φ store owed its migration migrates here (the keyspace's pass then waits for the
    next turn close), or keeps the φ sweep and says once why it waits; at idb-control the φ sweep and, once per verdict,
    the shadow migration's. Every call shares one deadline under the harness's limit, and a verdict that only changes
    with the φ store is re-earned only when that store changed, or once a day. Silent when nothing moved; every other
    outcome — moved, skipped for a lock, stopped at a gate, owed — is a line."""
    sid = str(payload.get("session_id") or "unknown")
    now = datetime.datetime.now()
    stamp = f"{now:{NOW_FMT}}"
    deadline = time.monotonic() + TURN_CLOSE_BUDGET_S

    def left():
        return deadline - time.monotonic()
    engine, _setting, _state = store_engine(store)
    reports = [f"turn-close: {l}" for l in gc_trace_lines(store, sid)]   # finalization: what no post-write saw

    def light():
        return run_idb(store, ["light", "--session", sid, "--now", stamp, "--budget-s", str(max(1, int(left()) - 10))],
                       "turn-close:", left())[1]
    if engine == "idb":
        reports.append(light())
    elif engine == "migrate":
        rc, line = run_idb(store, ["migrate", "--session", sid, "--now", stamp,
                                   "--budget-s", str(max(1, int(left()) - 10))], "migrate:", left())
        if rc == 0 and line.startswith("migrate: migrated"):
            reports.append("turn-close: " + line[len("migrate: "):] + " — the keyspace's first pass runs at the next "
                           "turn close")
        elif store_engine(store)[2] == "idb":
            # committed but unfinished: the keyspace's pass finishes it — never the φ sweep over an imported arc/
            reports.append("turn-close: " + (line[len("migrate: "):] if line else "migrated; its report was lost"))
            if left() > TURN_CLOSE_MIN_CALL_S:
                reports.append(light())
        else:
            if left() > TURN_CLOSE_MIN_CALL_S:
                reports.append(phi_light(store, sid, now, left()))
            if line and record_verdict(store, ".idb-migrate", "-", line):
                reports.append(f"turn-close: the migration to the keyspace waits — {line[len('migrate: '):]}")
    else:
        reports.append(phi_light(store, sid, now, left()))
        if engine == "shadow":
            fp = phi_fingerprint(store)
            if not verdict_stands(store, ".idb-shadow", fp) and left() > TURN_CLOSE_MIN_CALL_S:
                _rc, line = run_idb(store, ["migrate", "--shadow", "--session", sid, "--now", stamp,
                                            "--budget-s", str(max(1, int(left()) - 10))], "shadow:", left())
                transient = any(t in line for t in ("out of time", "skipped", "could not run", "failed (exit"))
                if line and not transient and record_verdict(store, ".idb-shadow", fp, line):
                    reports.append(f"turn-close: {line}")
    try:
        pt.build_vindex(store)      # the cumulative index over every session store; silent, never a report line
    except Exception:  # noqa: BLE001 — a hook degrades, never raises; the next turn close rebuilds it
        pass
    kept = [r for r in reports if r and not (r.startswith("turn-close: nothing to move") and "owed" not in r)]
    if kept:
        with open(os.path.join(store, TURN_CLOSE), "a", encoding="utf-8", newline="\n") as f:
            for r in kept:
                f.write(f"{sid} {stamp} {r[len('turn-close: '):]}\n")
    block = conductor_owed(payload, store, sid, stamp)
    if block:
        print(json.dumps({"decision": "block", "reason": block}))
    elif kept:
        print("\n".join(kept))
    return 0


POOL_OWED = ".pool-owed"    # the session ids whose first unpooled stop was blocked once — the second stop passes


def conductor_owed(payload, store, sid, stamp):
    """The reason to block this stop once, or None: the recall config names a conductor (`operator-via:`) on the
    pooled road and this session has no pool of its own yet, so its first moment never ran — the launch no hook can
    make (a hook has no channel to spawn a subagent), owed by the session before its turn ends. Once per session:
    a stop the hook already continued (`stop_hook_active`) and a session already blocked both pass, so a session
    without the conductor agent is never held in a loop."""
    if payload.get("stop_hook_active") or sid == "unknown" or not os.path.isdir(store):
        return None
    cfg = pt.config_index(store)
    _inject, _digest, _from, pool, models = recall_lists(read_text(cfg) if os.path.exists(cfg) else "")
    via = models.get("via")
    if pool != "subagent" or not via or pool_session(store) == sid[:8]:
        return None
    marker = os.path.join(store, POOL_OWED)
    seen = set(read_text(marker).split()) if os.path.exists(marker) else set()
    if sid in seen:
        return None
    with open(marker, "a", encoding="utf-8", newline="\n") as f:
        f.write(sid + "\n")
    brief = os.path.join(plugin_root(), "hooks", "operator-prompt.md")
    return (f"VLDS: this session's first moment never ran — the recall config names {via} as the conductor and "
            f"this session has no pool ({session_store_label(store)}recall-pool.md). Before ending the turn, launch "
            f"it: the Agent tool, subagent_type {via}, in the foreground, with one message — `Read {brief} and do what "
            f"it says. store: {store} | session: {sid[:8]} | now: {stamp} | moment: open | <this session's task in "
            f"one line, and the owner's words>` — and a last line `conductor: launch the operator with this message "
            f"on {models['pool']}, and return a derived understanding`; act on the derivation it returns, then finish "
            "the reply. This stop is blocked once per session; if the agent type is not available, say so and stop.")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:]
    sub = argv[0] if argv else ""
    slot = None
    if "--slot" in argv:
        try:
            slot = int(argv[argv.index("--slot") + 1])
        except (IndexError, ValueError):
            slot = None
    standing = None
    if "--standing" in argv:
        try:
            standing = int(argv[argv.index("--standing") + 1])
        except (IndexError, ValueError):
            standing = None
    payload = payload_from_stdin()
    store = resolve_store(payload)
    try:
        if sub == "session-open" and standing is not None:
            return cmd_session_standing(payload, store, standing)
        if sub == "session-open" and slot is not None:
            return cmd_session_slot(payload, store, slot)
        if sub == "session-open":
            return cmd_session_open(payload, store)
        if sub == "prompt-open":
            return cmd_prompt_open(payload, store)
        if sub == "pre-write":
            return cmd_pre_write(payload, store)
        if sub == "pre-ask":
            return cmd_pre_ask(payload, store)
        if sub == "pre-agent":
            return cmd_pre_agent(payload, store)
        if sub == "post-write":
            return cmd_post_write(payload, store)
        if sub == "turn-close":
            return cmd_turn_close(payload, store)
        print(f"vlds_hooks.py: unknown subcommand {sub!r}")
        return 0
    except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
        print(f"VLDS hook ({sub}) degraded: {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
