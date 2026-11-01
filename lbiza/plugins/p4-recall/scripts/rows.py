#!/usr/bin/env python3
"""rows.py: the message rows of `store/messages/<s8>.md` (fresh-marketplace.md 3.5, 5.1), `p4.py row open|close`.

open   the prompt hook stamps a row: `fingerprint:` (the message, quoted, at most 300 characters), `time:`,
       `arrival:` (turn, or notification for a harness message), and `resembles:` when an earlier completed row of
       the session resembles it (the old barrier's rule). A notification or agent message is complete on arrival:
       `state: FRESH` and an `addressed:` saying so.
close  the close hook completes the session's last open row from the reply: `state: FRESH` and `addressed:` (the
       reply's first paragraph, at most 300 characters). ECHO and SUPERSEDED are judged offline, never here.
Rows are appended or extended in place: no other line of the file is rewritten.
"""

import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ranker  # noqa: E402
import store as st  # noqa: E402

FP_CHARS = 300
ADDRESSED_CHARS = 300
HARNESS_RE = re.compile(r"^\s*<(task-notification|system-reminder|local-command|command-name|command-message|"
                        r"bash-input|bash-stdout|user-prompt-submit-hook)", re.I)


def session_file(p4, session):
    return os.path.join(st.store_dir(p4), st.MESSAGES, f"{(session or 'nosession')[:8]}.md")


def now_stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def quote(text, n):
    t = re.sub(r"\s+", " ", (text or "").replace('"', "'")).strip()
    return '"' + (t if len(t) <= n else t[:n - 1].rstrip() + "…") + '"'


def first_paragraph(reply):
    paras = [p.strip() for p in re.split(r"\n\s*\n", reply or "") if p.strip()]
    p = paras[0] if paras else ""
    p = re.sub(r"\s+", " ", p)
    return p if len(p) <= ADDRESSED_CHARS else p[:ADDRESSED_CHARS - 1].rstrip() + "…"


def row_open(p4, session, prompt, now=None, arrival=None):
    """Append the row; returns its entry id."""
    now = now or now_stamp()
    path = session_file(p4, session)
    rel = f"{st.MESSAGES}/{os.path.basename(path)}"
    is_harness = bool(HARNESS_RE.match(prompt or ""))
    arrival = arrival or ("notification" if is_harness else "turn")
    pairs = [("fingerprint", quote(prompt, FP_CHARS)), ("time", now), ("arrival", arrival)]
    old = st.parse(st.read_text(path), rel) if os.path.exists(path) else []
    if not is_harness:
        new = set(st.norm_token(prompt).split())
        for e in reversed(old):
            if st.completed(e) and st.owner_message(e) and st.resembles(
                    new, set(st.norm_token(st.unquote(e.fields.get("fingerprint", e.value))).split())):
                pairs.append(("resembles", e.id))
                break
    if arrival != "turn":
        pairs += [("state", "FRESH"), ("addressed", f"(a {arrival}; complete on arrival)")]
    text = st.read_text(path) if os.path.exists(path) else st.render(rel, [])
    text = text.rstrip("\n") + "\n\n" + st.format_entry(pairs) + "\n"
    ranker.write_atomic(path, text)
    got = st.parse(text, rel)
    return got[-1].id if got else ""


def row_close(p4, session, reply, now=None):
    """Complete the session's last open row from the reply; returns (row Entry before completion, completed?)."""
    path = session_file(p4, session)
    if not os.path.exists(path):
        return None, False
    rel = f"{st.MESSAGES}/{os.path.basename(path)}"
    text = st.read_text(path)
    ents = st.parse(text, rel)
    open_rows = [e for e in ents if not st.completed(e)]
    if not open_rows:
        return None, False
    e = open_rows[-1]
    addressed = first_paragraph(reply)
    if not addressed:
        return e, False
    lines = text.split("\n")
    j = e.line                          # the line after the head (0-based index e.line)
    while j < len(lines) and lines[j].startswith("  "):
        j += 1
    add = []
    if not e.fields.get("state", "").strip():
        add.append("  state: FRESH")
    add.append(f"  addressed: {addressed}")
    lines[j:j] = add
    ranker.write_atomic(path, "\n".join(lines))
    return e, True
