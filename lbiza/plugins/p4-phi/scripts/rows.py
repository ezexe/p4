#!/usr/bin/env python3
"""rows.py: the message rows of `phi/store/messages/<s8>.md`, one row for each message a session is sent.

open   the UserPromptSubmit hook `recall` stamps a row: `fingerprint:`, the message quoted and cut to 300
       characters, `time:` and `arrival:`. `arrival:` is `turn` for ezexe's message, `notification` for one that
       Claude Code wrote, whose text opens with a tag HARNESS_RE matches, and `agent message` for another
       session's and for the prompt of a turn p4-phi's hooks module started. A row of ezexe's also gets `resembles:`, naming the newest completed row of ezexe's in the
       session that resembles it by store.resembles. A notification is complete on arrival: `state: FRESH` and an
       `addressed:` saying so. Another session's message is answered like a turn: its row stays open to the turn end.
close  at the turn end, the Stop hook `close` completes the session's last open row from the reply: `state:`,
       `addressed:`, the reply's first paragraph cut to 300 characters, `recommended:`, the reply's first sentence
       that recommends something, cut to 300 characters and empty when none, and `match:` when the row's
       `resembles:` names a completed row. judge_state gives the state and `match:`.
Rows are appended or extended in place: no other line of the file changes.

`recommended:` takes its sentence from any paragraph, since a reply often states its recommendation after the
first. store.entry_text indexes it with the row's other text, so its words reach retrieval.
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
RECOMMENDED_CHARS = 300
HARNESS_RE = re.compile(r"^\s*(?:<(task-notification|system-reminder|local-command|command-name|command-message|"
                        r"bash-input|bash-stdout|user-prompt-submit-hook)|"
                        # the app's notice about a message this session sent, as plans.APP_NOTICE spells it
                        r"(?:\[MESSAGE FROM NON-USER SOURCE\b[^\]\n]*\]\s*)?\[Cross-session (?:delivery|idle) notice\])",
                        re.I)
PEER_RE = re.compile(r"^\s*(Another Claude session sent a message:\s*)?<cross-session-message\b", re.I)
# the prompt of a turn p4-phi's hooks module started: it opens with plans.WAKE_MARK, and its words are not ezexe's
WAKE_RE = re.compile(r"^\s*phi \(p4-phi\): the turn before this one ended on\b")
# a sentence that hands ezexe a recommendation: recommendation phrasing only, not every `should`
RECOMMEND_RE = re.compile(r"(?i)\b(recommend|suggest|better to|prefer(red|able)?|the right way|instead of|rather than|"
                          r"go with|best (way|option|practice)|i'?d (use|go|pick|keep|pin|set)|the fix is|"
                          r"(you|we) should|should (use|pin|keep|move|set|run|switch|avoid|not|stay|be))\b")
FENCE_RE = re.compile(r"```.*?```", re.S)
SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[`])|\n+")


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


def recommended_sentence(reply):
    """The reply's first sentence that RECOMMEND_RE finds, from any paragraph, fenced code left out and a question
    skipped, cut to RECOMMENDED_CHARS; '' when none."""
    text = FENCE_RE.sub(" ", reply or "")
    for s in SENTENCE_END_RE.split(text):
        s = re.sub(r"\s+", " ", s or "").strip()
        if s and not s.endswith("?") and RECOMMEND_RE.search(s):
            return s if len(s) <= RECOMMENDED_CHARS else s[:RECOMMENDED_CHARS - 1].rstrip() + "…"
    return ""


def row_open(p4, session, prompt, now=None, arrival=None):
    """Append the row; returns its entry id."""
    now = now or now_stamp()
    path = session_file(p4, session)
    rel = f"{st.MESSAGES}/{os.path.basename(path)}"
    is_harness = bool(HARNESS_RE.match(prompt or ""))
    # another session's message arrives as a turn and is answered like one, but its words are not ezexe's, and
    # neither are those of a turn the plugin's hooks module started
    is_peer = bool(PEER_RE.match(prompt or "") or WAKE_RE.match(prompt or ""))
    arrival = arrival or ("notification" if is_harness else "agent message" if is_peer else "turn")
    pairs = [("fingerprint", quote(prompt, FP_CHARS)), ("time", now), ("arrival", arrival)]
    old = st.parse(st.read_text(path), rel) if os.path.exists(path) else []
    if not is_harness and not is_peer:
        new = set(st.norm_token(prompt).split())
        for e in reversed(old):
            if st.completed(e) and st.owner_message(e) and st.resembles(
                    new, set(st.norm_token(st.unquote(e.fields.get("fingerprint", e.value))).split())):
                pairs.append(("resembles", e.id))
                break
    if arrival != "turn" and not is_peer:
        pairs += [("state", "FRESH"), ("addressed", f"(a {arrival}; complete on arrival)")]
    text = st.read_text(path) if os.path.exists(path) else st.render(rel, [])
    text = text.rstrip("\n") + "\n\n" + st.format_entry(pairs) + "\n"
    ranker.write_atomic(path, text)
    got = st.parse(text, rel)
    return got[-1].id if got else ""


def row_close(p4, session, reply, now=None):
    """Complete the session's last open row from the reply. Returns `(row, done)`: the row's Entry as it was before,
    None when the session has no open row, and whether the row was completed, which a reply with no text is not."""
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
    j = e.line                          # the line after the head: e.line counts the head's line from 1
    while j < len(lines) and lines[j].startswith("  "):
        j += 1
    add = []
    state, match = judge_state(e, ents, addressed)
    if not e.fields.get("state", "").strip():
        add.append(f"  state: {state}")
    add.append(f"  addressed: {addressed}")
    rec = recommended_sentence(reply)
    add.append(f"  recommended: {rec}" if rec else "  recommended:")
    if match:
        add.append(f"  match: {match}")
    lines[j:j] = add
    ranker.write_atomic(path, "\n".join(lines))
    return e, True


def task_kind(p4, session, row, prompt):
    """The task kind of a closed turn, as labels.task_of_row names it: `short` for a message of at most
    store.SHORT_WORDS words, `first` for the session's first row of ezexe's, with none of ezexe's before it in the
    session's file, else `new`."""
    if len(st.norm_token(prompt).split()) <= st.SHORT_WORDS:
        return "short"
    if row is not None:
        path = session_file(p4, session)
        ents = st.parse(st.read_text(path), f"{st.MESSAGES}/{os.path.basename(path)}") if os.path.exists(path) else []
        owner = [e for e in ents if st.owner_message(e)]
        if owner and owner[0].id == row.id:
            return "first"
    return "new"


def judge_state(e, ents, addressed):
    """`(state, match)` for a row being completed: ECHO when the earlier row its `resembles:` names got the same
    answer again, the two `addressed:` paragraphs alike by st.resembles; SUPERSEDED when that earlier row was
    answered anew; FRESH when its `resembles:` names no completed row. `match` names the earlier row by its time
    and says which of the two it was, in plain words; '' for FRESH."""
    rid = e.fields.get("resembles", "").strip()
    prior = next((x for x in ents if rid and x.id == rid and st.completed(x)), None)
    if prior is None:
        return "FRESH", ""
    new = set(st.norm_token(addressed).split())
    old = set(st.norm_token(prior.fields.get("addressed", "")).split())
    if st.resembles(new, old):
        return "ECHO", f"the {prior.time} row, the same answer again"
    return "SUPERSEDED", f"the {prior.time} row, answered anew"
